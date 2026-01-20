import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import pandas as pd
import streamlit as st
from packaging import version

# ---- Safety check for rich/streamlit combo
try:
    import rich as _rich
    if version.parse(_rich.__version__) >= version.parse("14.0.0"):
        st.warning(
            f"Detected rich {_rich.__version__}. Streamlit 1.37.0 requires rich<14. "
            "Fix with: pip install 'rich<14'"
        )
except Exception:
    pass

from utils.parsing import parse_keywords, parse_csv_locations
from utils.infer_beats import infer_topics_from_text, normalize_topics
from services.newsapi import fetch_newsapi_top_headlines, fetch_newsapi_everything
from services.perigon import fetch_perigon_stories

st.set_page_config(
    page_title="Reporter Identification Tool",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- Session State
defaults = {
    "keywords": "",
    "topics": [],
    "locations": "",
    "recency_days": 90,
    "strict": False,
    "use_newsapi": True,
    "use_perigon": True,
    "search_clicked": False,
    "last_results_articles": None,
    "last_results_reporters": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------- Sidebar: single source of truth
with st.sidebar:
    st.markdown("### Reporter Finder")
    st.caption("Enter keywords here; tabs change how results are displayed.")
    st.divider()

    st.session_state.keywords = st.text_input(
        "Keywords (primary)",
        value=st.session_state.keywords,
        placeholder="e.g., AI regulation, startups funding, antitrust, labor",
    )

    # Optional topic chips; if streamlit-tags isn't installed, we fall back to a plain text input
    topics: List[str] = []
    used_fallback = False
    try:
        from streamlit_tags import st_tags  # type: ignore
        suggested = [
            "ai", "machine learning", "startups", "labor", "antitrust", "privacy",
            "cybersecurity", "elections", "climate", "health", "finance", "politics",
            "technology", "media"
        ]
        topics = st_tags(
            label="Topics / beats (optional)",
            text="Add a topic and press Enter",
            value=st.session_state.topics,
            suggestions=suggested,
            maxtags=12,
            key="topics_tags",
        )
    except Exception:
        used_fallback = True
        topics_text = st.text_input(
            "Topics / beats (optional)",
            value=",".join(st.session_state.topics) if st.session_state.topics else "",
            placeholder="e.g., ai, technology, finance"
        )
        topics = parse_keywords(topics_text)

    st.session_state.topics = normalize_topics(topics)

    st.caption(
        "Topics are used as metadata **when available** (Perigon `topics`), "
        "otherwise they’re treated as extra keyword hints (NewsAPI)."
    )

    st.session_state.locations = st.text_input(
        "Locations (comma-separated)",
        value=st.session_state.locations,
        placeholder="e.g., New York, SF, London",
    )

    st.session_state.recency_days = st.slider(
        "Recency (days)",
        7, 365,
        int(st.session_state.recency_days),
        help="How recent should articles be? If results are empty, we can widen this automatically when Strict is off."
    )

    st.session_state.strict = st.toggle(
        "Strict filters",
        value=bool(st.session_state.strict),
        help="Off = broader results (topics/locations act as ranking boosts). On = apply filters strictly.",
    )

    st.divider()
    st.caption("Sources")
    col_a, col_b = st.columns(2)
    with col_a:
        st.session_state.use_newsapi = st.checkbox("NewsAPI", value=bool(st.session_state.use_newsapi))
    with col_b:
        st.session_state.use_perigon = st.checkbox("Perigon", value=bool(st.session_state.use_perigon))

    if used_fallback:
        st.caption("Tip: install optional dependency `streamlit-tags` for autocomplete chips.")

    st.divider()
    if st.button("Search", type="primary", use_container_width=True):
        st.session_state.search_clicked = True

# ---------------- Main
st.title("Reporter Identification Tool")
tab_reporter, tab_articles = st.tabs(["Reporter", "Articles"])

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _load_articles() -> pd.DataFrame:
    keywords = st.session_state.keywords.strip()
    topic_hints = st.session_state.topics
    recency_days = int(st.session_state.recency_days)
    locations = parse_csv_locations(st.session_state.locations)

    if not keywords and not topic_hints:
        return pd.DataFrame()

    query_terms = [t for t in parse_keywords(keywords) if t] + [t for t in topic_hints if t]
    query = " OR ".join([f'"{t}"' if " " in t else t for t in query_terms]) if query_terms else ""

    from_dt = _utc_now() - timedelta(days=recency_days)

    rows: List[Dict[str, Any]] = []

    if st.session_state.use_newsapi:
        newsapi_items: List[Dict[str, Any]] = []
        try:
            if keywords or topic_hints:
                newsapi_items = fetch_newsapi_everything(
                    q=query,
                    from_iso=_iso(from_dt),
                    language="en",
                    page_size=100,
                )
            else:
                newsapi_items = fetch_newsapi_top_headlines(country="us", page_size=100)
        except Exception as e:
            # Don't crash the app if NewsAPI is misconfigured or rate-limited.
            # Streamlit Cloud will redact the original exception message if we let it bubble.
            # Keep this message user-facing and safe (no URLs / apiKey).
            msg = str(e)
            status = ""
            if hasattr(e, "response") and getattr(e, "response") is not None:
                try:
                    status = f"HTTP {e.response.status_code}: "
                    # NewsAPI often returns JSON like {"status":"error","code":"...","message":"..."}
                    j = e.response.json()
                    if isinstance(j, dict) and j.get("message"):
                        msg = str(j.get("message"))
                except Exception:
                    pass
            st.warning(f"NewsAPI request failed. {status}{msg}")
            newsapi_items = []

        for a in newsapi_items:
            rows.append({
                "source_api": "NewsAPI",
                "source": (a.get("source") or {}).get("name"),
                "author": a.get("author"),
                "title": a.get("title"),
                "description": a.get("description"),
                "content": a.get("content"),
                "url": a.get("url"),
                "publishedAt": a.get("publishedAt"),
                "topics": None,
                "sentiment": None,
            })

    if st.session_state.use_perigon:
        perigon_items: List[Dict[str, Any]] = []
        try:
            perigon_items = fetch_perigon_stories(
                q=keywords or None,
                from_iso=_iso(from_dt),
                page_size=100,
            )
        except Exception as e:
            # Avoid leaking request URLs (which could contain apiKey) in error strings.
            msg = str(e)
            status = ""
            if hasattr(e, "response") and getattr(e, "response") is not None:
                try:
                    status = f"HTTP {e.response.status_code}: "
                    j = e.response.json()
                    if isinstance(j, dict) and (j.get("message") or j.get("error")):
                        msg = str(j.get("message") or j.get("error"))
                except Exception:
                    pass
            st.warning(f"Perigon request failed. {status}{msg}")
            perigon_items = []

        def _perigon_source_domain(a: dict) -> str:
            src = a.get("source")
            if isinstance(src, dict):
                return (src.get("domain") or src.get("name") or "").strip()
            return (str(src) if src else "").strip()

        def _perigon_author(a: dict) -> str:
            # Perigon commonly uses authorsByline; sometimes matchedAuthors.
            byline = (a.get("authorsByline") or a.get("author") or "").strip()
            if byline:
                return byline
            matched = a.get("matchedAuthors")
            if isinstance(matched, list) and matched:
                names = [str(m.get("name") or "").strip() for m in matched if isinstance(m, dict)]
                names = [n for n in names if n]
                return ", ".join(names)
            return ""

        def _perigon_topics(a: dict) -> List[str]:
            # Perigon can return topics/categories/taxonomies as lists of dicts with "name".
            out: List[str] = []
            for key in ("topics", "categories", "taxonomies"):
                val = a.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            name = item.get("name")
                            if name:
                                out.append(str(name))
                        elif item:
                            out.append(str(item))
            return out

        for a in perigon_items:
            rows.append({
                "source_api": "Perigon",
                "source": _perigon_source_domain(a),
                "author": _perigon_author(a),
                "title": a.get("title"),
                "description": a.get("description"),
                "content": a.get("content"),
                "url": a.get("url"),
                # Perigon uses pubDate (e.g. 2026-01-20T16:22:13+00:00)
                "publishedAt": a.get("pubDate") or a.get("publishedAt"),
                "topics": _perigon_topics(a),
                "sentiment": a.get("sentiment"),
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["publishedAt"] = pd.to_datetime(df["publishedAt"], errors="coerce", utc=True)

    def _topics_for_row(r) -> List[str]:
        if isinstance(r.get("topics"), list) and r["topics"]:
            return normalize_topics([str(x) for x in r["topics"] if x])
        text = " ".join([str(r.get("title") or ""), str(r.get("description") or ""), str(r.get("content") or "")])
        inferred = infer_topics_from_text(text, extra_hints=topic_hints)
        return normalize_topics(inferred)

    df["topics_norm"] = df.apply(_topics_for_row, axis=1)

    def _blob(r) -> str:
        return " ".join([str(r.get("title") or ""), str(r.get("description") or ""), str(r.get("content") or "")]).lower()

    blob = df.apply(_blob, axis=1)

    user_topics = set([t.lower() for t in topic_hints])
    user_locs = set([l.lower() for l in locations])

    def _topic_match_score(topics_list: List[str]) -> int:
        if not user_topics:
            return 0
        return sum(1 for t in topics_list if t.lower() in user_topics)

    df["topic_score"] = df["topics_norm"].apply(_topic_match_score)

    def _loc_score(text_l: str) -> int:
        if not user_locs:
            return 0
        return sum(1 for loc in user_locs if loc in text_l)

    df["loc_score"] = blob.apply(_loc_score)

    if st.session_state.strict:
        if user_topics:
            df = df[df["topic_score"] > 0].copy()
        if user_locs:
            df = df[df["loc_score"] > 0].copy()

    df = df.dropna(subset=["url"]).drop_duplicates(subset=["url"]).copy()

    if st.session_state.strict:
        df = df.sort_values(["publishedAt"], ascending=[False])
    else:
        df = df.sort_values(["topic_score", "loc_score", "publishedAt"], ascending=[False, False, False])

    return df

def _reporters_from_articles(df_articles: pd.DataFrame) -> pd.DataFrame:
    if df_articles.empty:
        return pd.DataFrame(columns=["author", "source", "articles", "last_seen", "topics"])

    d = df_articles.copy()
    d["author"] = d["author"].fillna("").astype(str).str.strip()
    d = d[d["author"] != ""].copy()

    if d.empty:
        return pd.DataFrame(columns=["author", "source", "articles", "last_seen", "topics"])

    def _top_topics(series_of_lists: pd.Series, n: int = 5) -> List[str]:
        counts = {}
        for lst in series_of_lists.dropna():
            for t in (lst or []):
                counts[t] = counts.get(t, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]]

    grouped = d.groupby(["author", "source"], dropna=False).agg(
        articles=("url", "count"),
        last_seen=("publishedAt", "max"),
        topics=("topics_norm", _top_topics),
    ).reset_index()

    grouped = grouped.sort_values(["articles", "last_seen"], ascending=[False, False])
    return grouped

def _ensure_results():
    if not st.session_state.search_clicked:
        return

    df = _load_articles()

    if df.empty and not st.session_state.strict and int(st.session_state.recency_days) < 365:
        widened = min(365, int(st.session_state.recency_days) + 180)
        st.session_state.recency_days = widened
        df = _load_articles()

    st.session_state.last_results_articles = df
    st.session_state.last_results_reporters = _reporters_from_articles(df)
    st.session_state.search_clicked = False

_ensure_results()

df_articles: Optional[pd.DataFrame] = st.session_state.last_results_articles
df_reporters: Optional[pd.DataFrame] = st.session_state.last_results_reporters

with tab_reporter:
    st.subheader("Reporters")
    if df_reporters is None:
        st.info("Enter keywords in the sidebar and click Search.")
    else:
        st.caption("Authors are aggregated from returned articles. NewsAPI often has missing authors; Perigon usually provides them.")
        st.dataframe(df_reporters, use_container_width=True)
        if not df_reporters.empty:
            csv = df_reporters.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, "reporters.csv", "text/csv")

with tab_articles:
    st.subheader("Articles")
    if df_articles is None:
        st.info("Enter keywords in the sidebar and click Search.")
    else:
        view = df_articles.copy()
        view["topics"] = view["topics_norm"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
        view = view.drop(columns=["topics_norm"], errors="ignore")
        st.dataframe(view, use_container_width=True)
        if not view.empty:
            csv = view.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, "articles.csv", "text/csv")

st.caption("Theme + search UX updated: single sidebar keyword search, Perigon topics used when present, otherwise inferred.")
