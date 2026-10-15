"""Airflow DAG: weekly retraining of the Voyage Analytics flight price model.

validate_data -> prepare_data -> train_model -> evaluate_model -> quality_gate
                                                                  |-> register_model -> promote_model -> report
                                                                  '-> reject_model ----------------------> report
"""
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.models.param import Param
from airflow.operators.python import get_current_context

import voyage_ml as ml

default_args = {
    'owner': 'voyage-analytics',
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}


def _run_id():
    return get_current_context()['run_id']


@dag(
    dag_id='flight_price_retraining',
    description='Validate data, retrain the flight price model, compare with production and promote if better',
    schedule='@weekly',
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=['voyage', 'mlops', 'retraining'],
    doc_md=__doc__,
    params={   # editable in the UI via "Trigger DAG w/ config"; raise min_r2 above 1 to demo a rejection
        'min_r2': Param(0.99, type='number', minimum=0, maximum=2, description='Minimum test R2 to accept the new model'),
        'mae_tolerance': Param(0.5, type='number', minimum=0, description='How much worse than production the MAE may be'),
    },
)
def flight_price_retraining():

    @task
    def validate_data():
        """Fail fast if the data file is missing or malformed."""
        return ml.validate_data(_run_id())

    @task
    def prepare_data(_validation):
        return ml.prepare_data(_run_id())

    @task
    def train_model(_split):
        return ml.train_model(_run_id())

    @task
    def evaluate_model(candidate):
        params = get_current_context()['params']
        return ml.evaluate_model(_run_id(), candidate, float(params['min_r2']), float(params['mae_tolerance']))

    @task.branch
    def quality_gate(evaluation):
        """Route to promotion only if the candidate passed the quality checks."""
        return 'register_model' if evaluation['passed'] else 'reject_model'

    @task
    def register_model(candidate, evaluation, validation):
        return ml.register_model(_run_id(), candidate, evaluation, validation)

    @task
    def promote_model(_registered, candidate, evaluation):
        return ml.promote_model(_run_id(), candidate, evaluation)

    @task
    def reject_model(evaluation):
        return {'promoted': False, 'reasons': evaluation['reasons']}

    @task(trigger_rule='none_failed_min_one_success')
    def report(validation, evaluation):
        ctx = get_current_context()
        ti = ctx['ti']
        promoted = ti.xcom_pull(task_ids='promote_model')
        outcome = (f"promoted as model version {promoted['model_version']}" if promoted
                   else 'rejected - production model kept')
        return ml.write_report(_run_id(), validation, evaluation, outcome)

    validation = validate_data()
    split = prepare_data(validation)
    candidate = train_model(split)
    evaluation = evaluate_model(candidate)
    gate = quality_gate(evaluation)

    registered = register_model(candidate, evaluation, validation)
    promoted = promote_model(registered, candidate, evaluation)
    rejected = reject_model(evaluation)
    gate >> [registered, rejected]

    final = report(validation, evaluation)
    [promoted, rejected] >> final


flight_price_retraining()
