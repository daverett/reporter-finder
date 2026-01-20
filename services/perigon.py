import os
from typing import Any, Dict, List, Optional

import requests

# Perigon API base. The endpoint you tested uses:
#   https://api.perigon.io/v1/articles/all?...
PERIGON_BASE = os.getenv("PERIGON_BASE_URL", "https://api.perigon.io")

def _key() -> str:
    k = os.getenv("PERIGON_KEY") or os.getenv("PERIGON_API_KEY")
    if not k:
        raise RuntimeError("Missing Perigon key. Set PERIGON_KEY (or PERIGON_API_KEY) in env or Streamlit secrets.")
    return k

def fetch_perigon_stories(
    q: Optional[str] = None,
    from_iso: Optional[str] = None,
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    """Fetch articles from Perigon.

    Notes:
      - Perigon uses an `apiKey` query param (not Bearer auth).
      - The primary endpoint is /v1/articles/all.
    """

    url = f"{PERIGON_BASE}/v1/articles/all"

    params = {
        "apiKey": _key(),
        "language": "en",
        "sortBy": "date",
        "showNumResults": "true",
        "page": 0,
        "size": int(page_size),
        "showReprints": "false",
    }
    if q:
        params["q"] = q
    if from_iso:
        params["from"] = from_iso

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    # Perigon responses commonly use `articles`.
    return data.get("articles") or data.get("results") or []
