# Voyage Analytics - automated retraining with Airflow

DAG `flight_price_retraining` (weekly, or triggered by hand):

```
validate_data -> prepare_data -> train_model -> evaluate_model -> quality_gate
                                                                  |-> register_model -> promote_model -> report
                                                                  '-> reject_model ----------------------> report
```

| Task | What it does |
|---|---|
| validate_data | Checks flights_clean.csv exists, has the model columns, no missing values, positive prices/distances, enough rows |
| prepare_data | Fixed-seed 80/20 split saved for this run |
| train_model | Trains the XGBoost pipeline with the tuned parameters stored in the production model's metadata |
| evaluate_model | Scores the new model AND the current production model on the same test set |
| quality_gate | Branch: promote only if R2 >= min_r2 and MAE is not worse than production by more than mae_tolerance |
| register_model | Logs params/metrics/model to MLflow (DagsHub if MLFLOW_TRACKING_URI is set) and registers `flight-price-model` |
| promote_model | Backs up the old model, replaces `api/models/flight_price_model.joblib`, bumps `model_version` in the metadata |
| reject_model | Keeps the production model and records why |
| report | Writes `runs/<run_id>/report.md` |

Trigger settings (UI: Trigger DAG w/ config): `min_r2` (default 0.99), `mae_tolerance` (default 0.5).
Set `min_r2` to 1.5 to demonstrate a rejected model.

Files: `dags/flight_price_retraining.py` (the DAG), `dags/voyage_ml.py` (the ML logic), `start_airflow.sh` (runs Airflow 2.10.5 in Docker),
`data/` (put flights_clean.csv here), `runs/` (per-run reports and artifacts).
