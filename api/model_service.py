"""Loads the three Voyage Analytics models once and exposes validated prediction functions.

Model files are expected in ./models (created by setup_models.py):
  flight_price_model.joblib, route_distance.csv, model_metadata.json
  gender_classifier.joblib, gender_label_encoder.joblib, gender_model_metadata.json
  hotel_recommender.joblib, recommender.py, hotel_catalog.csv, recommender_metadata.json
"""
import json
import logging
import os
import sys

import joblib
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MODEL_DIR = os.environ.get('MODEL_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models'))
# recommender.py must be importable for the pickled recommender object to load
if MODEL_DIR not in sys.path:
    sys.path.insert(0, MODEL_DIR)


class ValidationError(ValueError):
    """Raised for bad user input; the API turns it into an HTTP 400 response."""


def _path(name):
    return os.path.join(MODEL_DIR, name)


def _read_json(name):
    with open(_path(name)) as f:
        return json.load(f)


class ModelService:
    def __init__(self):
        self.status = {}
        self._load_price()
        self._load_gender()
        self._load_recommender()

    # ------------------------------------------------------------------ loading
    def _load_price(self):
        try:
            self.price_model = joblib.load(_path('flight_price_model.joblib'))
            self.route_distance = pd.read_csv(_path('route_distance.csv'))
            self.price_meta = _read_json('model_metadata.json')
            self.status['flight_price'] = 'loaded'
        except Exception as e:  # keep the API up even if one model is missing
            self.price_model = None
            self.status['flight_price'] = f'not loaded: {e}'
            log.exception('Flight price model failed to load')

    def _load_gender(self):
        try:
            self.gender_model = joblib.load(_path('gender_classifier.joblib'))
            self.gender_encoder = joblib.load(_path('gender_label_encoder.joblib'))
            self.gender_meta = _read_json('gender_model_metadata.json')
            self.gender_features = self.gender_meta['derived_features']
            self.status['gender'] = 'loaded'
        except Exception as e:
            self.gender_model = None
            self.status['gender'] = f'not loaded: {e}'
            log.exception('Gender model failed to load')

    def _load_recommender(self):
        try:
            self.recommender = joblib.load(_path('hotel_recommender.joblib'))
            self.hotel_catalog = pd.read_csv(_path('hotel_catalog.csv'))
            self.reco_meta = _read_json('recommender_metadata.json')
            self.status['hotel_recommender'] = 'loaded'
        except Exception as e:
            self.recommender = None
            self.status['hotel_recommender'] = f'not loaded: {e}'
            log.exception('Hotel recommender failed to load')

    @property
    def healthy(self):
        return all(v == 'loaded' for v in self.status.values())

    def _require(self, model, name):
        if model is None:
            raise RuntimeError(f'{name} model is not available: {self.status.get(name)}')

    # ------------------------------------------------------------------ options for UIs
    def options(self):
        out = {}
        if self.price_model is not None:
            out['flight'] = {
                'cities': self.price_meta['valid_values']['from'],
                'flight_types': self.price_meta['valid_values']['flightType'],
                'agencies': self.price_meta['valid_values']['agency'],
                'agency_classes': self.price_meta['agency_classes'],
            }
        if self.gender_model is not None:
            out['gender'] = {'companies': self.gender_meta.get('known_companies', []),
                             'classes': self.gender_meta['classes']}
        if self.recommender is not None:
            out['hotels'] = self.hotel_catalog.to_dict(orient='records')
        return out

    # ------------------------------------------------------------------ flight price
    def predict_price(self, payload):
        self._require(self.price_model, 'flight_price')
        origin = _text(payload, 'from')
        destination = _text(payload, 'to')
        flight_type = _text(payload, 'flightType')
        agency = _text(payload, 'agency')
        valid = self.price_meta['valid_values']
        for field, value in [('from', origin), ('to', destination), ('flightType', flight_type), ('agency', agency)]:
            if value not in valid[field]:
                raise ValidationError(f"Invalid {field} '{value}'. Valid values: {valid[field]}")
        if origin == destination:
            raise ValidationError('from and to must be different cities')
        allowed = self.price_meta['agency_classes'].get(agency, [])
        if flight_type not in allowed:
            raise ValidationError(f'{agency} only sells {allowed} tickets')
        row = self.route_distance[(self.route_distance['from'] == origin) & (self.route_distance['to'] == destination)]
        if row.empty:
            raise ValidationError(f'No route data for {origin} -> {destination}')
        distance = float(row['distance'].iloc[0])
        X = pd.DataFrame([{'from': origin, 'to': destination, 'flightType': flight_type,
                           'agency': agency, 'distance': distance}])
        price = float(self.price_model.predict(X)[0])
        return {'from': origin, 'to': destination, 'flightType': flight_type, 'agency': agency,
                'distance_km': round(distance, 2), 'predicted_price': round(price, 2)}

    # ------------------------------------------------------------------ gender
    def predict_gender(self, payload):
        self._require(self.gender_model, 'gender')
        name = _text(payload, 'name')
        first = ''.join(ch for ch in name.split()[0].lower() if ch.isalpha()) if name.split() else ''
        if not first:
            raise ValidationError('name must contain letters')
        try:
            age = int(payload.get('age'))
        except (TypeError, ValueError):
            raise ValidationError('age must be a whole number')
        if not 1 <= age <= 119:
            raise ValidationError('age must be between 1 and 119')
        company = str(payload.get('company') or 'unknown').strip()
        row = pd.DataFrame([{'first_name': first, 'last_letter': first[-1],
                             'ends_vowel': int(first[-1] in 'aeiouy'), 'name_len': len(first),
                             'age': age, 'company': company}])
        proba = self.gender_model.predict_proba(row[self.gender_features])[0]
        classes = [str(c) for c in self.gender_encoder.classes_]
        return {'name': name, 'predicted_gender': classes[int(np.argmax(proba))],
                'probabilities': {c: round(float(p), 3) for c, p in zip(classes, proba)},
                'note': self.gender_meta.get('responsible_use', '')}

    # ------------------------------------------------------------------ hotels
    def recommend_hotels(self, payload):
        self._require(self.recommender, 'hotel_recommender')
        cities = set(self.hotel_catalog['place'])
        try:
            user = int(payload.get('userCode', -1))
        except (TypeError, ValueError):
            raise ValidationError('userCode must be a whole number (use -1 for a new user)')
        origin = payload.get('origin') or None
        destination = payload.get('destination') or None
        for label, city in [('origin', origin), ('destination', destination)]:
            if city is not None and city not in cities:
                raise ValidationError(f"Unknown {label} city '{city}'. Valid: {sorted(cities)}")
        if origin and destination and origin == destination:
            raise ValidationError('origin and destination must differ')
        max_price = payload.get('max_price')
        if max_price not in (None, ''):
            try:
                max_price = float(max_price)
            except (TypeError, ValueError):
                raise ValidationError('max_price must be a number')
            if max_price <= 0:
                raise ValidationError('max_price must be positive')
        else:
            max_price = None
        try:
            k = int(payload.get('k', 3))
        except (TypeError, ValueError):
            raise ValidationError('k must be a whole number')
        if not 1 <= k <= len(self.hotel_catalog):
            raise ValidationError(f'k must be between 1 and {len(self.hotel_catalog)}')
        recs = self.recommender.recommend(user, origin=origin, destination=destination, max_price=max_price, k=k)
        known = user in getattr(self.recommender, 'user_index_', {})
        return {'userCode': user, 'known_user': bool(known), 'origin': origin, 'destination': destination,
                'max_price': max_price, 'recommendations': recs.to_dict(orient='records')}


def _text(payload, field):
    value = payload.get(field)
    if value is None or not str(value).strip():
        raise ValidationError(f"'{field}' is required")
    return str(value).strip()
