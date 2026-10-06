# AI Climate & SDG Action Map · Team SapioCoders (Hack4SDG)

Click any place in India to see its heat, flood and drought risk, the SDGs it affects, actions and what-if results,
explained by number-checked AI. Data: NASA POWER · Copernicus DEM · MODIS NDVI · WorldPop · Open-Meteo.

## Put it online (Streamlit Community Cloud, free)
1. Upload everything in this folder to a new public GitHub repo (keep the folder structure).
2. Go to share.streamlit.io → Create app → pick the repo, branch `main`, main file `streamlit_app.py` → Deploy.
3. Optional: in the app's Settings → Secrets add `GEMINI_API_KEY = "..."`. Without it the free Pollinations AI is used.

Run locally: `pip install -r requirements.txt` then `streamlit run streamlit_app.py`.

Scores are relative indicators for prioritisation, not forecasts.
