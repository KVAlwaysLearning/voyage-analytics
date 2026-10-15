#!/usr/bin/env bash
# Starts Airflow (all-in-one "standalone" mode) in Docker for the Voyage Analytics retraining DAG.
# Run from anywhere:  bash airflow/start_airflow.sh
set -euo pipefail
cd "$(dirname "$0")"                       # the airflow/ folder
REPO="$(cd .. && pwd)"

if [ ! -f data/flights_clean.csv ]; then
  echo "ERROR: airflow/data/flights_clean.csv is missing - unzip it from processed.zip first."; exit 1
fi
if [ ! -f "$REPO/api/requirements.txt" ] || [ ! -f "$REPO/api/models/flight_price_model.joblib" ]; then
  echo "ERROR: api/requirements.txt or api/models/ not found - complete Day 4 first."; exit 1
fi

# Use the SAME ML library versions as the API, so models promoted by Airflow load in the API
ML_REQS="$(grep -E '^(numpy|pandas|scikit-learn|scipy|xgboost|xgboost-cpu)==' "$REPO/api/requirements.txt" | tr '\n' ' ')"
echo "ML libraries for Airflow: $ML_REQS"

mkdir -p runs
docker rm -f airflow >/dev/null 2>&1 || true
docker run -d --name airflow \
  -p 8081:8080 \
  --user "$(id -u):0" \
  -e AIRFLOW__CORE__LOAD_EXAMPLES=False \
  -e AIRFLOW__WEBSERVER__EXPOSE_CONFIG=False \
  -e _PIP_ADDITIONAL_REQUIREMENTS="$ML_REQS mlflow-skinny<3 joblib" \
  -e MLFLOW_TRACKING_URI="${MLFLOW_TRACKING_URI:-}" \
  -e MLFLOW_TRACKING_USERNAME="${MLFLOW_TRACKING_USERNAME:-}" \
  -e MLFLOW_TRACKING_PASSWORD="${MLFLOW_TRACKING_PASSWORD:-}" \
  -v "$PWD/dags:/opt/airflow/dags" \
  -v "$PWD/data:/opt/airflow/data" \
  -v "$PWD/runs:/opt/airflow/runs" \
  -v "$REPO/api/models:/opt/airflow/production_models" \
  apache/airflow:2.10.5-python3.12 standalone

echo
echo "Airflow is starting (installing ML libraries first takes 2-4 minutes)."
echo "Follow progress with:   docker logs -f airflow"
echo "Login password:         docker exec airflow cat /opt/airflow/standalone_admin_password.txt"
echo "Open the UI:            PORTS tab -> port 8081 -> globe icon (user: admin)"
