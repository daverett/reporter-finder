import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import pandas as pd
import streamlit as st

from utils.parsing import parse_keywords, parse_csv_locations
from utils.infer_beats import infer_topics_from_text, normalize_topics
from services.newsapi import fetch_newsapi_everything, NewsAPIError
from services.perigon import fetch_perigon_articles_all, PerigonError


st.set_page_config(
    page_title="Reporter Identification Tool",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Theme hardening
# If Streamlit Cloud isn't picking up .streamlit/config.toml (e.g., file not committed or theme overridden),
# force the primary color via CSS so buttons/highlights are consistently #045359.
st.markdown(
    """
    <style>
      :root { --primary-color: #045359; }
      .stButton>button {
        background-color: #045359 !important;
        border-color: #045359 !important;
      }
      .stButton>button:hover {
        filter: brightness(0.95);
      }
      /* Selected tabs / accents */
      div[data-baseweb="tab"] button[aria-selected="true"] {
        color: #045359 !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# NewsAPI free/dev plans often restrict how far back you can query.
NEWSAPI_FREE_MAX_DAYS = 29


# ---------------- Session State
defaults = {
    "keywords": "",
    "topics": [],
    "locations": "",
    "recency_days": 30,
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

st.expander("Theme debug", expanded=False).write(
    {
        "theme.primaryColor (active)": st.get_option("theme.primaryColor"),
        "theme.base": st.get_option("theme.base"),
        "config file expected at": ".streamlit/config.toml",
    }
)

    st.session_state.keywords = st.text_input(
        "Keywords (primary)",
        value=st.session_state.keywords,
        placeholder="e.g., AI regulation, healthcare, antitrust, labor",
    )

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
        "Topics are used as metadata **when available** (Perigon taxonomies/topics), "
        "otherwise they’re treated as extra keyword hints (NewsAPI)."
    )

    st.session_state.locations = st.text_input(
        "Locations (comma-separated)",
        value=st.session_state.locations,
        placeholder="e.g., New York, SF, London",
    )

    st.session_state.recency_days = st.slider(
        "Recency (days)",
        1, 365,
        int(st.session_state.recency_days),
        help="NewsAPI free plan usually only supports the last ~30 days on /everything.",
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
        st.caption("Note: missing bootstrap.min.css.map warnings from streamlit-tags are harmless on Streamlit Cloud.")

    # Friendly warning if NewsAPI selected with recency too high
    if st.session_state.use_newsapi and int(st.session_state.recency_days) > NEWSAPI_FREE_MAX_DAYS:
        st.warning(
            f"NewsAPI /everything is often limited to the last ~{NEWSAPI_FREE_MAX_DAYS} days on free/dev plans. "
            "We’ll cap the NewsAPI date range automatically."
        )

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

def _safe_str(x) -> str:
    return "" if x is None else str(x)

def _load_articles() -> pd.DataFrame:
    keywords = st.session_state.keywords.strip()
    topic_hints = st.session_state.topics
    recency_days = int(st.session_state.recency_days)
    locations = parse_csv_locations(st.session_state.locations)

    if not keywords and not topic_hints:
        return pd.DataFrame()

    # Build query string (NewsAPI expects a single q)
    query_terms = [t for t in parse_keywords(keywords) if t] + [t for t in topic_hints if t]
    query = " OR ".join([f'"{t}"' if " " in t else t for t in query_terms]) if query_terms else ""

    from_dt = _utc_now() - timedelta(days=recency_days)

    rows: List[Dict[str, Any]] = []

    # --- NewsAPI
    if st.session_state.use_newsapi:
        # Cap 'from' for NewsAPI free plan compatibility
        news_from_dt = max(from_dt, _utc_now() - timedelta(days=NEWSAPI_FREE_MAX_DAYS))
        news_from_iso = _iso(news_from_dt)

        api_key = os.getenv("NEWSAPI_KEY") or os.getenv("NEWS_API_KEY")
        if not api_key:
            st.warning("Missing NewsAPI key. Set NEWS_API_KEY in Streamlit secrets.")
        else:
            try:
                newsapi_items = fetch_newsapi_everything(
                    api_key=api_key,
                    q=query,
                    from_iso=news_from_iso,
                    language="en",
                    page_size=100,
                )
            except NewsAPIError as e:
                st.warning(str(e))
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
                    "topics_raw": None,      # NewsAPI: no topics metadata in response
                    "sentiment": None,
                })

    # --- Perigon
    if st.session_state.use_perigon:
        api_key = os.getenv("PERIGON_API_KEY") or os.getenv("PERIGON_KEY")
        if not api_key:
            st.warning("Missing Perigon key. Set PERIGON_API_KEY in Streamlit secrets.")
        else:
            try:
                perigon_items = fetch_perigon_articles_all(
                    api_key=api_key,
                    q=keywords or None,
                    language="en",
                    sort_by="date",
                    from_iso=_iso(from_dt),
                    page=0,
                    size=100,
                    show_num_results=True,
                    show_reprints=False,
                )
            except PerigonError as e:
                st.warning(str(e))
                perigon_items = []

            for a in perigon_items:
                src = a.get("source") or {}
                # Author normalization: prefer authorsByline, fallback to matchedAuthors names
                author = a.get("authorsByline")
                if not author:
                    ma = a.get("matchedAuthors") or []
                    if isinstance(ma, list) and ma:
                        names = [m.get("name") for m in ma if isinstance(m, dict) and m.get("name")]
                        author = ", ".join(names) if names else None

                # Topics: prefer topics/categories/taxonomies/keywords if present
                topics = []
                for key in ("topics", "categories"):
                    lst = a.get(key) or []
                    if isinstance(lst, list) and lst:
                        topics.extend([x.get("name") for x in lst if isinstance(x, dict) and x.get("name")])
                tax = a.get("taxonomies") or []
                if isinstance(tax, list) and tax:
                    # keep top few by score if present
                    tax_sorted = sorted(
                        [x for x in tax if isinstance(x, dict) and x.get("name")],
                        key=lambda x: float(x.get("score", 0) or 0),
                        reverse=True,
                    )
                    topics.extend([x.get("name") for x in tax_sorted[:6]])
                kw = a.get("keywords") or []
                if isinstance(kw, list) and kw:
                    kw_sorted = sorted(
                        [x for x in kw if isinstance(x, dict) and x.get("name")],
                        key=lambda x: float(x.get("weight", 0) or 0),
                        reverse=True,
                    )
                    topics.extend([x.get("name") for x in kw_sorted[:6]])

                rows.append({
                    "source_api": "Perigon",
                    "source": src.get("domain") or src.get("title") or a.get("sourceName"),
                    "author": author,
                    "title": a.get("title"),
                    "description": a.get("description"),
                    "content": a.get("content"),
                    "url": a.get("url"),
                    "publishedAt": a.get("pubDate") or a.get("publishedAt"),
                    "topics_raw": topics or None,
                    "sentiment": a.get("sentiment"),
                })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["publishedAt"] = pd.to_datetime(df["publishedAt"], errors="coerce", utc=True)

    # Normalize topics: use metadata when present, else infer from text
    def _topics_for_row(r) -> List[str]:
        raw = r.get("topics_raw")
        if isinstance(raw, list) and raw:
            return normalize_topics([_safe_str(x) for x in raw if x])
        text = " ".join([_safe_str(r.get("title")), _safe_str(r.get("description")), _safe_str(r.get("content"))])
        inferred = infer_topics_from_text(text, extra_hints=topic_hints)
        return normalize_topics(inferred)

    df["topics_norm"] = df.apply(_topics_for_row, axis=1)

    # Location scoring/filtering (simple keyword contains)
    def _blob(r) -> str:
        return " ".join([_safe_str(r.get("title")), _safe_str(r.get("description")), _safe_str(r.get("content"))]).lower()

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

    return grouped.sort_values(["articles", "last_seen"], ascending=[False, False])

def _ensure_results():
    if not st.session_state.search_clicked:
        return

    df = _load_articles()

    # Wider recency only helps Perigon; NewsAPI is capped anyway
    if df.empty and not st.session_state.strict and int(st.session_state.recency_days) < 365:
        st.session_state.recency_days = min(365, int(st.session_state.recency_days) + 30)
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

with tab_articles:
    st.subheader("Articles")
    if df_articles is None:
        st.info("Enter keywords in the sidebar and click Search.")
    else:
        view = df_articles.copy()
        view["topics"] = view["topics_norm"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
        view = view.drop(columns=["topics_norm"], errors="ignore")
        st.dataframe(view, use_container_width=True)

st.caption("Fix: NewsAPI 426 errors are handled gracefully + date range is capped for free plan. Theme primary color: #045359.")
