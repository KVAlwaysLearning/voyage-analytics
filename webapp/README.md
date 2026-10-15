# Voyage Analytics web app

A static site (HTML + CSS + JavaScript, no build step) that calls the Voyage Analytics API.

| Tab | What it does | API endpoint |
|---|---|---|
| Fare estimate | Route, airline and class → fare shown as a boarding pass | `POST /predict/price` |
| Hotel picks | Traveller + departure city + budget → ranked hotels with reasons | `POST /recommend/hotels` |
| Name check | Name, age, company → probability of each gender label | `POST /predict/gender` |
| Insights | Charts from the EDA (data/insights.json, no API needed) | – |
| Models | Model metrics, registry names and the MLOps pipeline | – |

Files: `index.html`, `styles.css`, `app.js`, `config.js` (API address), `data/insights.json`.

The only file you edit is **config.js**: put your API's Render URL in it.
For a quick test without editing, add `?api=https://your-api.onrender.com` to the page address.
