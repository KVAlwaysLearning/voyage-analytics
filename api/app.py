"""Voyage Analytics REST API (Flask).

Endpoints
  GET  /                  API info
  GET  /health            liveness + which models are loaded (used by Docker / Kubernetes probes)
  GET  /options           valid values for dropdowns in the web app
  POST /predict/price     {"from", "to", "flightType", "agency"}
  POST /predict/gender    {"name", "age", "company"}
  POST /recommend/hotels  {"userCode", "origin"?, "destination"?, "max_price"?, "k"?}
"""
import logging
import os
import time

from flask import Flask, jsonify, request
from flask_cors import CORS

from model_service import ModelService, ValidationError

logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'),
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('voyage-api')

app = Flask(__name__)
CORS(app)                       # allow the Render web app (another domain) to call the API from the browser
service = ModelService()        # models are loaded once at start-up
START_TIME = time.time()
VERSION = os.environ.get('APP_VERSION', '1.0.0')


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError('Request body must be a JSON object')
    return data


@app.errorhandler(ValidationError)
def handle_validation(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(RuntimeError)
def handle_unavailable(e):
    return jsonify(error=str(e)), 503


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error='Not found. See GET / for available endpoints.'), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error='Method not allowed for this endpoint.'), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    log.exception('Unhandled error')
    return jsonify(error='Internal server error'), 500


@app.get('/')
def index():
    return jsonify(
        name='Voyage Analytics API', version=VERSION,
        endpoints={
            'GET /health': 'service status',
            'GET /options': 'valid input values',
            'POST /predict/price': {'from': 'Recife (PE)', 'to': 'Florianopolis (SC)', 'flightType': 'firstClass', 'agency': 'FlyingDrops'},
            'POST /predict/gender': {'name': 'Maria Silva', 'age': 34, 'company': '4You'},
            'POST /recommend/hotels': {'userCode': 0, 'origin': 'Recife (PE)', 'max_price': 250, 'k': 3},
        })


@app.get('/health')
def health():
    body = dict(status='ok' if service.healthy else 'degraded', models=service.status,
                version=VERSION, uptime_seconds=round(time.time() - START_TIME, 1),
                pod=os.environ.get('HOSTNAME', 'local'))   # shows which replica answered (useful on Kubernetes)
    return jsonify(body), (200 if service.healthy else 503)


@app.get('/options')
def options():
    return jsonify(service.options())


@app.post('/predict/price')
def predict_price():
    return jsonify(service.predict_price(_json_body()))


@app.post('/predict/gender')
def predict_gender():
    return jsonify(service.predict_gender(_json_body()))


@app.post('/recommend/hotels')
def recommend_hotels():
    return jsonify(service.recommend_hotels(_json_body()))


if __name__ == '__main__':
    # Local development only; Docker uses gunicorn (see Dockerfile)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
