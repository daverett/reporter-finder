import os
from typing import Any, Dict, List, Optional
import requests

NEWSAPI_BASE = "https://newsapi.org/v2"

def _key() -> str:
    k = os.getenv("NEWSAPI_KEY") or os.getenv("NEWS_API_KEY")
    if not k:
        raise RuntimeError("Missing NewsAPI key. Set NEWSAPI_KEY (or NEWS_API_KEY) in env or Streamlit secrets.")
    return k

def fetch_newsapi_top_headlines(country: str = "us", page_size: int = 100) -> List[Dict[str, Any]]:
    url = f"{NEWSAPI_BASE}/top-headlines"
    params = {"country": country, "pageSize": page_size, "apiKey": _key()}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("articles") or []

def fetch_newsapi_everything(
    q: str,
    from_iso: Optional[str] = None,
    language: str = "en",
    page_size: int = 100,
    sort_by: str = "publishedAt",
) -> List[Dict[str, Any]]:
    url = f"{NEWSAPI_BASE}/everything"
    params = {
        "q": q,
        "language": language,
        "pageSize": page_size,
        "sortBy": sort_by,
        "apiKey": _key(),
    }
    if from_iso:
        params["from"] = from_iso
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("articles") or []
