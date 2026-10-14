"""API tests - run with:  pytest -q
They load the real models from ./models, so run setup_models.py first.
These tests are also what the CI/CD pipeline (Day 9) runs before building the Docker image."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app  # noqa: E402


@pytest.fixture()
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_health(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.get_json()['status'] == 'ok'


def test_options(client):
    body = client.get('/options').get_json()
    assert len(body['flight']['cities']) == 9
    assert len(body['hotels']) == 9


def test_price_valid(client):
    r = client.post('/predict/price', json={'from': 'Recife (PE)', 'to': 'Florianopolis (SC)',
                                            'flightType': 'firstClass', 'agency': 'FlyingDrops'})
    assert r.status_code == 200
    assert abs(r.get_json()['predicted_price'] - 1434.38) < 1.0     # known fare from the data


@pytest.mark.parametrize('payload, message', [
    ({'from': 'Natal (RN)', 'to': 'Natal (RN)', 'flightType': 'economic', 'agency': 'Rainbow'}, 'different'),
    ({'from': 'Recife (PE)', 'to': 'Natal (RN)', 'flightType': 'economic', 'agency': 'FlyingDrops'}, 'only sells'),
    ({'from': 'Paris', 'to': 'Natal (RN)', 'flightType': 'economic', 'agency': 'Rainbow'}, 'Invalid from'),
    ({'to': 'Natal (RN)', 'flightType': 'economic', 'agency': 'Rainbow'}, 'required'),
])
def test_price_invalid(client, payload, message):
    r = client.post('/predict/price', json=payload)
    assert r.status_code == 400
    assert message in r.get_json()['error']


def test_gender(client):
    r = client.post('/predict/gender', json={'name': 'Patricia Gomes', 'age': 30, 'company': '4You'})
    assert r.status_code == 200
    body = r.get_json()
    assert body['predicted_gender'] in ('female', 'male', 'none')
    assert abs(sum(body['probabilities'].values()) - 1) < 0.01


def test_gender_invalid_age(client):
    r = client.post('/predict/gender', json={'name': 'Ana', 'age': 'abc'})
    assert r.status_code == 400


def test_recommend_known_user_excludes_origin(client):
    r = client.post('/recommend/hotels', json={'userCode': 0, 'origin': 'Recife (PE)', 'k': 8})
    assert r.status_code == 200
    body = r.get_json()
    assert body['known_user'] is True
    assert all(h['city'] != 'Recife (PE)' for h in body['recommendations'])


def test_recommend_new_user_with_budget(client):
    r = client.post('/recommend/hotels', json={'userCode': -1, 'max_price': 200, 'k': 3})
    body = r.get_json()
    assert r.status_code == 200 and body['known_user'] is False
    assert all(h['price_per_night'] <= 200 for h in body['recommendations'])


def test_recommend_invalid_city(client):
    assert client.post('/recommend/hotels', json={'userCode': 1, 'origin': 'Paris'}).status_code == 400


def test_bad_json_and_404(client):
    assert client.post('/predict/price', data='not json', content_type='text/plain').status_code == 400
    assert client.get('/nope').status_code == 404
