# Reporter Identification Tool (Streamlit)

## What changed in this version
- **Single keyword search** in the left sidebar + one **Search** button.
- Removed duplicate keyword inputs in the main panels.
- Theme updated: primary color is now **#045359** (buttons/highlights).
- Perigon `topics` are used when present; NewsAPI has no topics metadata, so topics are inferred from text.

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export NEWSAPI_KEY="..."
export PERIGON_KEY="..."
streamlit run app.py
```

## Streamlit Cloud
Commit `.streamlit/config.toml` and `requirements.txt`, then set secrets:
- `NEWSAPI_KEY`
- `PERIGON_KEY`

## Notes
- The Perigon endpoint in `services/perigon.py` is set to `${PERIGON_BASE_URL}/all` by default.
  If your existing integration uses `/stories` (or another path), update that file accordingly.
