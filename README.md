# Reporter Finder — Articles & Reporters (with Date Filters, Caching, Scoring)

Two-tab Streamlit app:
- **Articles**: merged NewsAPI + Perigon article results (date range supported)
- **Reporters**: aggregated by author with outlet weighting and scoring modes (frequency/prominence/recency/hybrid)
- Caching to reduce API calls
- Optional enrichment: Hunter.io emails, Perigon journalist profile lookup

## Secrets
Add these in Streamlit Secrets:

```
NEWS_API_KEY = "your_newsapi_key"
PERIGON_API_KEY = "your_perigon_key"
HUNTER_API_KEY = "your_hunter_key"  # optional
APP_USERNAME = "admin"               # optional
APP_PASSWORD = "change-me"           # optional
```
