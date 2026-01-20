from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests


class NewsAPIError(RuntimeError):
    """Raised when NewsAPI request fails in a way we want to surface safely."""


def fetch_newsapi_everything(
    api_key: str,
    q: str,
    from_iso: Optional[str] = None,
    language: str = "en",
    sort_by: str = "publishedAt",
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    url = "https://newsapi.org/v2/everything"
    params: Dict[str, Any] = {
        "q": q,
        "language": language,
        "pageSize": page_size,
        "sortBy": sort_by,
        "apiKey": api_key,
    }
    if from_iso:
        params["from"] = from_iso

    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code >= 400:
            msg = ""
            try:
                data = r.json() or {}
                msg = (data.get("message") or data.get("code") or "").strip()
            except Exception:
                msg = ""

            if r.status_code == 426:
                raise NewsAPIError(
                    "NewsAPI returned 426 (Upgrade Required). On free/dev plans this often happens when "
                    "the request isn't allowed (e.g., too old date range or production restrictions)."
                )
            if r.status_code == 401:
                raise NewsAPIError("NewsAPI returned 401 (Unauthorized). Check NEWS_API_KEY.")
            if r.status_code == 429:
                raise NewsAPIError("NewsAPI returned 429 (Rate limit). Try again later.")
            raise NewsAPIError(f"NewsAPI request failed ({r.status_code}). {msg}".strip())

        data = r.json()
        return data.get("articles") or []

    except requests.RequestException as e:
        raise NewsAPIError("NewsAPI request failed due to a network/timeout error.") from e
