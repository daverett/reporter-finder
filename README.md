# Reporter Finder — Streamlit Web App (No Clearbit)

Find journalists writing about a topic, enrich with emails (Hunter.io only).

## Deploy on Streamlit Cloud
1. Push this repo to GitHub.
2. Go to https://share.streamlit.io → **New App** → pick your repo.
3. Add secrets in Streamlit Cloud → Settings → Secrets:
   ```
   NEWS_API_KEY = "your-newsapi-key"
   HUNTER_API_KEY = "your-hunter-key"
   APP_USERNAME = "admin"
   APP_PASSWORD = "change-me"
   ```
4. Click **Deploy**.

✅ Secrets are stored server-side — not in GitHub.
