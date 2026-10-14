# Voyage Analytics API

One Flask REST API serving the three Voyage Analytics models:

| Endpoint | Body (JSON) | Returns |
|---|---|---|
| `GET /` | – | API info + example requests |
| `GET /health` | – | status of each model, version, uptime, pod name |
| `GET /options` | – | valid cities, classes, agencies, companies, hotel catalogue (for dropdowns) |
| `POST /predict/price` | `{"from": "Recife (PE)", "to": "Florianopolis (SC)", "flightType": "firstClass", "agency": "FlyingDrops"}` | predicted ticket price |
| `POST /predict/gender` | `{"name": "Maria Silva", "age": 34, "company": "4You"}` | predicted class + probabilities |
| `POST /recommend/hotels` | `{"userCode": 0, "origin": "Recife (PE)", "destination": null, "max_price": 250, "k": 3}` | top-k hotels with reasons (`userCode: -1` = new user) |

Invalid input → HTTP 400 with an `error` message. A model that failed to load → HTTP 503.

## Files

```
api/
├── app.py               Flask routes, error handling, CORS
├── model_service.py     loads the models once + input validation + predictions
├── setup_models.py      unpacks the 3 Colab zips into models/ and pins library versions
├── requirements.txt     written by setup_models.py
├── requirements-dev.txt adds pytest for testing
├── Dockerfile           production image (gunicorn, non-root user, health check)
├── .dockerignore
├── tests/test_api.py    13 automated tests
└── models/              created by setup_models.py
```

## Day 4 steps (all in GitHub Codespaces, in the browser)

**1. Open your Codespace.** github.com → your `voyage-analytics` repo → **Code → Codespaces → Create codespace on main**.

**2. Add this project.** In the Codespace file explorer (left), right-click the empty area → **Upload…** and upload `voyage-api.zip`. Then in the terminal:
```bash
unzip voyage-api.zip -d api && cd api
```

**3. Add the model zips.** Upload `flight_price_outputs.zip`, `gender_outputs.zip` and `recommender_outputs.zip` into the `api` folder (right-click `api` → Upload…), then:
```bash
python setup_models.py
```
It copies the model files into `models/`, and pins scikit-learn / xgboost / numpy / pandas / scipy **and the Python version** to exactly what Colab used.

**4. Test without Docker (optional but quick).**
```bash
pip install -r requirements-dev.txt
pytest -q                     # expect: 13 passed
```

**5. Build and run the Docker image.**
```bash
docker build -t voyage-api:1.0 .
docker run -d --name voyage-api -p 5000:5000 voyage-api:1.0
sleep 10 && docker ps         # STATUS should become "(healthy)" after ~40 s
```

**6. Call the API.**
```bash
curl localhost:5000/health
curl -X POST localhost:5000/predict/price -H "Content-Type: application/json" \
     -d '{"from":"Sao Paulo (SP)","to":"Salvador (BH)","flightType":"economic","agency":"Rainbow"}'
curl -X POST localhost:5000/predict/gender -H "Content-Type: application/json" \
     -d '{"name":"Isabella Santos","age":29,"company":"Acme Factory"}'
curl -X POST localhost:5000/recommend/hotels -H "Content-Type: application/json" \
     -d '{"userCode":0,"origin":"Recife (PE)","max_price":250,"k":3}'
docker logs voyage-api        # gunicorn access log
```
Codespaces also shows a **Ports** tab; open port 5000 in the browser to see `GET /`.

**7. Push the image to Docker Hub** (replace `YOUR_DOCKERHUB_USERNAME`):
```bash
docker login                  # Docker Hub username + password (or an access token)
docker tag voyage-api:1.0 YOUR_DOCKERHUB_USERNAME/voyage-api:1.0
docker tag voyage-api:1.0 YOUR_DOCKERHUB_USERNAME/voyage-api:latest
docker push YOUR_DOCKERHUB_USERNAME/voyage-api:1.0
docker push YOUR_DOCKERHUB_USERNAME/voyage-api:latest
```

**8. Save your work in the repo** (needed for Render, Kubernetes and CI later — the `.gitignore` keeps the large zips out):
```bash
cd .. && git add api && git commit -m "Day 4: Flask API + Dockerfile" && git push
```

**9. Clean up and stop the Codespace** to save free hours:
```bash
docker stop voyage-api && docker rm voyage-api
```
Then github.com/codespaces → … → **Stop codespace**.

## Screenshots to keep for the report
- `pytest -q` showing 13 passed
- `docker build` finishing and `docker ps` showing **(healthy)**
- the three `curl` responses
- your image on hub.docker.com
