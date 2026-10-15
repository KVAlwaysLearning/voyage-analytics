"""Training, evaluation and promotion logic for the flight price retraining DAG.

Kept separate from the DAG file so the logic can be unit-tested and reused (e.g. by CI).
All paths come from environment variables so the same code runs locally and in Docker.
"""
import json
import logging
import os
import shutil
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DATA_FILE = os.environ.get('VOYAGE_DATA_FILE', '/opt/airflow/data/flights_clean.csv')
RUNS_DIR = os.environ.get('VOYAGE_RUNS_DIR', '/opt/airflow/runs')
PROD_DIR = os.environ.get('VOYAGE_PROD_MODEL_DIR', '/opt/airflow/production_models')

FEATURES = ['from', 'to', 'flightType', 'agency', 'distance']
CAT_FEATURES = ['from', 'to', 'flightType', 'agency']
TARGET = 'price'
REQUIRED_COLUMNS = FEATURES + [TARGET]
DEFAULT_PARAMS = {'n_estimators': 600, 'max_depth': 8, 'learning_rate': 0.2, 'subsample': 0.8}

# Quality gate: a candidate is promoted only if it is accurate AND not worse than production
MIN_R2 = 0.99
MAE_TOLERANCE = 0.5            # candidate MAE may exceed production MAE by at most this many currency units


def save_model(model, path):
    """Save with Python's built-in C pickler.

    Airflow imports `dill`, which patches the pure-Python pickler (and joblib's copy of it) so that saved
    files would need dill to load. The C pickler (`pickle.dump`) cannot be patched that way, and
    `joblib.load` in the API reads plain pickle files, so the saved model stays dill-free."""
    import pickle
    with open(path, 'wb') as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)


def run_dir(run_id):
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in run_id)
    path = os.path.join(RUNS_DIR, safe)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------- 1. validate
def validate_data(run_id):
    """Check the training file exists and looks right before spending time on training."""
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f'Training data not found at {DATA_FILE}')
    df = pd.read_csv(DATA_FILE)
    problems = []
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        problems.append(f'missing columns: {missing_cols}')
    else:
        if len(df) < 1000:
            problems.append(f'too few rows: {len(df)}')
        nulls = int(df[REQUIRED_COLUMNS].isnull().sum().sum())
        if nulls:
            problems.append(f'{nulls} missing values in model columns')
        if (df[TARGET] <= 0).any():
            problems.append('non-positive prices found')
        if (df['distance'] <= 0).any():
            problems.append('non-positive distances found')
    if problems:
        raise ValueError('Data validation failed: ' + '; '.join(problems))
    stats = {
        'rows': int(len(df)),
        'price_mean': round(float(df[TARGET].mean()), 2),
        'price_min': round(float(df[TARGET].min()), 2),
        'price_max': round(float(df[TARGET].max()), 2),
        'categories': {c: int(df[c].nunique()) for c in CAT_FEATURES},
    }
    with open(os.path.join(run_dir(run_id), 'data_validation.json'), 'w') as f:
        json.dump(stats, f, indent=2)
    log.info('Data OK: %s', stats)
    return stats


# ---------------------------------------------------------------- 2. split
def prepare_data(run_id, test_size=0.2, seed=42):
    """Fixed-seed 80/20 split saved to the run folder, so training and evaluation use identical data."""
    from sklearn.model_selection import train_test_split
    df = pd.read_csv(DATA_FILE, usecols=REQUIRED_COLUMNS)
    train, test = train_test_split(df, test_size=test_size, random_state=seed)
    d = run_dir(run_id)
    train.to_csv(os.path.join(d, 'train.csv'), index=False)
    test.to_csv(os.path.join(d, 'test.csv'), index=False)
    log.info('Split: %d train / %d test rows', len(train), len(test))
    return {'train_rows': len(train), 'test_rows': len(test)}


# ---------------------------------------------------------------- 3. train
def _production_params():
    """Reuse the tuned hyper-parameters stored with the production model (from the Day 2 notebook)."""
    try:
        with open(os.path.join(PROD_DIR, 'model_metadata.json')) as f:
            params = json.load(f).get('best_params') or {}
        return {**DEFAULT_PARAMS, **params}
    except FileNotFoundError:
        return dict(DEFAULT_PARAMS)


def train_model(run_id, seed=42):
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder
    from xgboost import XGBRegressor

    d = run_dir(run_id)
    train = pd.read_csv(os.path.join(d, 'train.csv'))
    params = _production_params()
    model = Pipeline([
        ('pre', ColumnTransformer([('cat', OneHotEncoder(handle_unknown='ignore'), CAT_FEATURES),
                                   ('num', 'passthrough', ['distance'])])),
        ('model', XGBRegressor(**params, n_jobs=-1, random_state=seed)),
    ])
    start = datetime.now(timezone.utc)
    model.fit(train[FEATURES], train[TARGET])
    seconds = (datetime.now(timezone.utc) - start).total_seconds()
    path = os.path.join(d, 'candidate_model.joblib')
    save_model(model, path)
    log.info('Trained candidate in %.1fs with %s', seconds, params)
    return {'model_path': path, 'params': params, 'train_seconds': round(seconds, 1)}


# ---------------------------------------------------------------- 4. evaluate
def _metrics(y, pred):
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    return {'r2': round(float(r2_score(y, pred)), 6), 'mae': round(float(mean_absolute_error(y, pred)), 4),
            'rmse': round(float(np.sqrt(mean_squared_error(y, pred))), 4)}


def evaluate_model(run_id, candidate, min_r2=MIN_R2, mae_tolerance=MAE_TOLERANCE):
    """Score the candidate and the current production model on the SAME test set and apply the quality gate."""
    d = run_dir(run_id)
    test = pd.read_csv(os.path.join(d, 'test.csv'))
    cand_model = joblib.load(candidate['model_path'])
    cand = _metrics(test[TARGET], cand_model.predict(test[FEATURES]))

    prod = None
    prod_path = os.path.join(PROD_DIR, 'flight_price_model.joblib')
    if os.path.exists(prod_path):
        try:
            prod = _metrics(test[TARGET], joblib.load(prod_path).predict(test[FEATURES]))
        except Exception as e:     # e.g. incompatible library versions - treat as "no usable production model"
            log.warning('Could not score the production model: %s', e)

    reasons = []
    if cand['r2'] < min_r2:
        reasons.append(f"R2 {cand['r2']} is below the minimum {min_r2}")
    if prod is not None and cand['mae'] > prod['mae'] + mae_tolerance:
        reasons.append(f"MAE {cand['mae']} is worse than production {prod['mae']} (+{mae_tolerance} tolerance)")
    result = {'candidate': cand, 'production': prod, 'passed': not reasons, 'gate': {'min_r2': min_r2, 'mae_tolerance': mae_tolerance},
              'reasons': reasons or ['meets R2 threshold and is not worse than production']}
    with open(os.path.join(d, 'evaluation.json'), 'w') as f:
        json.dump(result, f, indent=2)
    log.info('Evaluation: %s', result)
    return result


# ---------------------------------------------------------------- 5a. register in MLflow
def register_model(run_id, candidate, evaluation, validation):
    """Log the run to MLflow and register the model. Uses DagsHub if MLFLOW_TRACKING_URI is set, else a local store."""
    import mlflow
    import mlflow.sklearn
    uri = os.environ.get('MLFLOW_TRACKING_URI') or 'file:' + os.path.join(RUNS_DIR, 'mlruns')
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment('flight-price-retraining')
    model = joblib.load(candidate['model_path'])
    with mlflow.start_run(run_name=f'airflow_{run_id}') as r:
        mlflow.set_tags({'trigger': 'airflow', 'airflow_run_id': run_id})
        mlflow.log_params({**candidate['params'], 'rows': validation['rows']})
        mlflow.log_metrics({f'test_{k}': v for k, v in evaluation['candidate'].items()})
        if evaluation['production']:
            mlflow.log_metrics({f'production_{k}': v for k, v in evaluation['production'].items()})
        mlflow.sklearn.log_model(model, artifact_path='model', registered_model_name='flight-price-model')
        info = {'tracking_uri': uri if uri.startswith('file:') else uri.split('@')[-1], 'mlflow_run_id': r.info.run_id}
    log.info('Registered in MLflow: %s', info)
    return info


# ---------------------------------------------------------------- 5b. promote to production
def promote_model(run_id, candidate, evaluation):
    """Back up the current production model, then replace it with the candidate and update its metadata."""
    d = run_dir(run_id)
    os.makedirs(PROD_DIR, exist_ok=True)
    backup = os.path.join(d, 'previous_production')
    os.makedirs(backup, exist_ok=True)
    meta_path = os.path.join(PROD_DIR, 'model_metadata.json')
    for name in ('flight_price_model.joblib', 'model_metadata.json'):
        src = os.path.join(PROD_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup, name))

    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    version = int(meta.get('model_version', 1)) + 1
    meta.update({
        'model_version': version,
        'trained_by': 'airflow:flight_price_retraining',
        'airflow_run_id': run_id,
        'trained_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'test_metrics': {'R2': evaluation['candidate']['r2'], 'MAE': evaluation['candidate']['mae'],
                         'RMSE': evaluation['candidate']['rmse']},
        'best_params': candidate['params'],
    })
    shutil.copy2(candidate['model_path'], os.path.join(PROD_DIR, 'flight_price_model.joblib'))
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    log.info('Promoted candidate as model version %d', version)
    return {'promoted': True, 'model_version': version, 'backup': backup}


# ---------------------------------------------------------------- 6. report
def write_report(run_id, validation, evaluation, outcome):
    d = run_dir(run_id)
    cand, prod = evaluation['candidate'], evaluation['production'] or {}
    lines = [
        f'# Flight price retraining - {run_id}', '',
        f"- Data rows: {validation['rows']:,} (price {validation['price_min']} to {validation['price_max']})",
        f"- Candidate: R2 {cand['r2']}, MAE {cand['mae']}, RMSE {cand['rmse']}",
        f"- Production: R2 {prod.get('r2', 'n/a')}, MAE {prod.get('mae', 'n/a')}, RMSE {prod.get('rmse', 'n/a')}",
        f"- Quality gate: {'PASSED' if evaluation['passed'] else 'FAILED'} ({'; '.join(evaluation['reasons'])})",
        f"- Outcome: {outcome}",
    ]
    for tmp in ('train.csv', 'test.csv'):          # keep run folders small
        p = os.path.join(d, tmp)
        if os.path.exists(p):
            os.remove(p)
    with open(os.path.join(d, 'report.md'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    log.info('\n'.join(lines))
    return outcome
