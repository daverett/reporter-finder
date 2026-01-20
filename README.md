# Reporter Identification Tool (Streamlit) — v2.3

## What this fixes
- NewsAPI `/everything` can return **426 Upgrade Required** on free/dev plans (often due to plan restrictions and/or date limits).
  This version:
  - caps NewsAPI's `from` date to the last ~29 days, and
  - catches NewsAPI errors so the app **doesn't crash** (Perigon can still return results).

- The `streamlit-tags` missing `bootstrap.min.css.map` warning in Streamlit Cloud logs is harmless; it does not affect functionality.

## Secrets (Streamlit Cloud)
- `NEWS_API_KEY`
- `PERIGON_API_KEY`

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
