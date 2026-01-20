from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests


class PerigonError(RuntimeError):
    """Raised when Perigon request fails in a way we want to surface safely."""


def fetch_perigon_articles_all(
    api_key: str,
    q: Optional[str] = None,
    language: str = "en",
    sort_by: str = "date",
    from_iso: Optional[str] = None,
    page: int = 0,
    size: int = 25,
    show_num_results: bool = True,
    show_reprints: bool = False,
) -> List[Dict[str, Any]]:
    url = "https://api.perigon.io/v1/articles/all"
    params: Dict[str, Any] = {
        "language": language,
        "sortBy": sort_by,
        "showNumResults": str(show_num_results).lower(),
        "page": page,
        "size": size,
        "showReprints": str(show_reprints).lower(),
        "apiKey": api_key,
    }
    if q:
        params["q"] = q
    if from_iso:
        params["from"] = from_iso

    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code >= 400:
            msg = ""
            try:
                data = r.json() or {}
                msg = (data.get("message") or data.get("error") or "").strip()
            except Exception:
                msg = ""
            raise PerigonError(f"Perigon request failed ({r.status_code}). {msg}".strip())

        data = r.json() or {}
        # Real endpoint uses "articles"
        return data.get("articles") or data.get("results") or []

    except requests.RequestException as e:
        raise PerigonError("Perigon request failed due to a network/timeout error.") from e
