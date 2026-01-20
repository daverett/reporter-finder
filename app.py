import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

def load_css(path: str) -> None:
    css_path = Path(path)
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

load_css("assets/custom.css")

NEWSAPI_FREE_MAX_DAYS = 29

# ---------------- Author/source hygiene
ORG_SUFFIXES = (
    " llp", " llc", " inc", " ltd", " plc", " gmbh", " corp", " corporation", " company",
    " partners", " partner", " group", " holdings", " capital", " management", " advisory",
)
NON_PERSON_KEYWORDS = (
    "newswire", "prnewswire", "press release", "pressrelease", "wire", "staff", "editorial",
    "desk", "team", "report", "reports", "announcement", "contributors", "contributor",
)

WIRE_SOURCE_HINTS = (
    "globenewswire", "prnewswire", "businesswire", "accesswire", "einpresswire",
    "newsfile", "benzinga", "marketscreener",
)

# Hard blocklist (Option B): iterate on this list over time.
# Use exact matches (lowercased, stripped). Add more as you discover them.
BLOCKED_AUTHORS = {
    "scienmag",
    "globe newswire",
    "globenewswire",
    "newsfinal journal",
}

BLOCKED_AUTHOR_CONTAINS = (
    # contains-based blocks for common wire-ish bylines
    "globenewswire",
    "prnewswire",
    "businesswire",
)

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _safe_str(x) -> str:
    return "" if x is None else str(x)

def is_blocked_author(name: Optional[str]) -> bool:
    if not name:
        return False
    low = name.strip().lower()
    if not low:
        return False
    if low in BLOCKED_AUTHORS:
        return True
    if any(s in low for s in BLOCKED_AUTHOR_CONTAINS):
        return True
    return False

def is_likely_person(name: Optional[str]) -> bool:
    if not name:
        return False
    n = name.strip()
    if not n:
        return False
    low = n.lower()

    if is_blocked_author(n):
        return False

    if any(k in low for k in NON_PERSON_KEYWORDS):
        return False
    if any(low.endswith(s) or f" {s.strip()}" in low for s in ORG_SUFFIXES):
        return False

    if low in {"reuters", "associated press", "ap", "bbc news", "cnn", "axios"}:
        return False

    if "@" in low or "http" in low or ".com" in low:
        return False

    letters = sum(ch.isalpha() for ch in n)
    if letters < max(4, int(len(n) * 0.5)):
        return False

    tokens = re.split(r"\s+", n)
    if len(tokens) == 1:
        return tokens[0][0].isupper() and tokens[0].isalpha() and len(tokens[0]) >= 3

    if len(tokens) > 5:
        return False

    if all(t.isupper() for t in tokens if t):
        return False

    return True

def classify_wire_pr(source: str, author: str, title: str) -> bool:
    blob = " ".join([source, author, title]).lower()
    if any(h in blob for h in WIRE_SOURCE_HINTS):
        return True
    if "press release" in blob or "prnewswire" in blob:
        return True
    if any(sfx in author.lower() for sfx in (" llp", " llc", " inc", " ltd")):
        return True
    return False

def extract_matched_terms(text: str, terms: List[str]) -> List[str]:
    t = text.lower()
    hit = []
    for term in terms:
        if not term:
            continue
        if term.lower() in t:
            hit.append(term.lower())
    seen = set()
    out = []
    for h in hit:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out

def highlight_terms(text: str, terms: List[str], max_len: int = 140) -> str:
    if not text:
        return ""
    s = str(text)
    out = s
    for term in sorted({t for t in terms if t}, key=len, reverse=True):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        out = pattern.sub(lambda m: f"«{m.group(0)}»", out)
    if len(out) > max_len:
        out = out[: max_len - 1] + "…"
    return out

# ---------------- Session State
defaults = {
    "keywords": "",
    "topics": [],
    "locations": "",
    "recency_days": 30,
    "strict": False,
    # Temporarily disable NewsAPI by default for cleaner debugging
    "use_newsapi": False,
    "use_perigon": True,
    "hide_non_person": True,
    "separate_wires": True,
    "search_clicked": False,
    "last_results_articles": None,
    "last_results_reporters": None,
    "last_results_wires": None,
    "last_query_terms": [],
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------- Sidebar
with st.sidebar:
    st.markdown("### Reporter Finder")
    st.caption("Enter keywords here; tabs change how results are displayed.")
    st.divider()

    st.session_state.keywords = st.text_input(
        "Keywords (primary)",
        value=st.session_state.keywords,
        placeholder="e.g., healthcare policy, hospital merger, insurance",
    )

    topics: List[str] = []
    used_fallback = False
    try:
        from streamlit_tags import st_tags  # type: ignore
        suggested = [
            "healthcare", "insurance", "hospitals", "biotech", "pharma",
            "ai", "privacy", "cybersecurity", "finance", "politics", "technology",
        ]
        topics = st_tags(
            label="Topics / beats (optional)",
            text="Add a topic and press Enter",
            value=st.session_state.topics,
            suggestions=suggests := suggested,
            maxtags=12,
            key="topics_tags",
        )
    except Exception:
        used_fallback = True
        topics_text = st.text_input(
            "Topics / beats (optional)",
            value=",".join(st.session_state.topics) if st.session_state.topics else "",
            placeholder="e.g., healthcare, insurance, biotech"
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
    st.caption("Quality filters")
    st.session_state.hide_non_person = st.checkbox(
        "Hide non-person authors (recommended)",
        value=bool(st.session_state.hide_non_person),
        help="Hides items like 'GlobeNewswire', PR firms, desks, and organizations.",
    )
    st.session_state.separate_wires = st.checkbox(
        "Separate wire / PR sources into their own tab",
        value=bool(st.session_state.separate_wires),
        help="Keeps press releases and wire content out of the Reporters tab (still accessible).",
    )

    st.divider()
    st.caption("Sources (NewsAPI disabled by default)")
    col_a, col_b = st.columns(2)
    with col_a:
        st.session_state.use_newsapi = st.checkbox("NewsAPI", value=bool(st.session_state.use_newsapi))
    with col_b:
        st.session_state.use_perigon = st.checkbox("Perigon", value=bool(st.session_state.use_perigon))

    if used_fallback:
        st.caption("Note: missing bootstrap.min.css.map warnings from streamlit-tags are harmless on Streamlit Cloud.")

    if st.session_state.use_newsapi and int(st.session_state.recency_days) > NEWSAPI_FREE_MAX_DAYS:
        st.warning(
            f"NewsAPI /everything is often limited to the last ~{NEWSAPI_FREE_MAX_DAYS} days on free/dev plans. "
            "We’ll cap the NewsAPI date range automatically."
        )

    st.divider()
    if st.button("Search", type="primary", use_container_width=True):
        st.session_state.search_clicked = True

    st.expander("Theme debug", expanded=False).write(
        {
            "theme.primaryColor (active)": st.get_option("theme.primaryColor"),
            "theme.base": st.get_option("theme.base"),
            "config file expected at": ".streamlit/config.toml",
        }
    )

# ---------------- Main
st.title("Reporter Identification Tool")

tab_reporter, tab_articles, tab_wires = st.tabs(["Reporters", "Articles", "Wires / PR"])

def _build_query_terms() -> List[str]:
    kws = parse_keywords(st.session_state.keywords.strip())
    return [k for k in kws if k]

def _load_articles() -> pd.DataFrame:
    keywords = st.session_state.keywords.strip()
    topic_hints = st.session_state.topics
    recency_days = int(st.session_state.recency_days)

    if not keywords and not topic_hints:
        return pd.DataFrame()

    query_terms = [t for t in parse_keywords(keywords) if t] + [t for t in topic_hints if t]
    query = " OR ".join([f'"{t}"' if " " in t else t for t in query_terms]) if query_terms else ""

    from_dt = _utc_now() - timedelta(days=recency_days)
    rows: List[Dict[str, Any]] = []

    # --- NewsAPI (optional)
    if st.session_state.use_newsapi:
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
                    "topics_raw": None,
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

                # Author normalization: prefer matchedAuthors (names) over authorsByline
                author = None
                ma = a.get("matchedAuthors") or []
                if isinstance(ma, list) and ma:
                    names = [m.get("name") for m in ma if isinstance(m, dict) and m.get("name")]
                    author = ", ".join(names) if names else None
                if not author:
                    author = a.get("authorsByline") or a.get("author")

                topics = []
                for key in ("topics", "categories"):
                    lst = a.get(key) or []
                    if isinstance(lst, list) and lst:
                        topics.extend([x.get("name") for x in lst if isinstance(x, dict) and x.get("name")])
                tax = a.get("taxonomies") or []
                if isinstance(tax, list) and tax:
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

    def _topics_for_row(r) -> List[str]:
        raw = r.get("topics_raw")
        if isinstance(raw, list) and raw:
            return normalize_topics([_safe_str(x) for x in raw if x])
        text = " ".join([_safe_str(r.get("title")), _safe_str(r.get("description")), _safe_str(r.get("content"))])
        inferred = infer_topics_from_text(text, extra_hints=topic_hints)
        return normalize_topics(inferred)

    df["topics_norm"] = df.apply(_topics_for_row, axis=1)

    # Relevance evidence (primary keyword terms only)
    primary_terms = st.session_state.last_query_terms or []
    if primary_terms:
        df["_blob"] = df.apply(lambda r: " ".join([_safe_str(r.get("title")), _safe_str(r.get("description")), _safe_str(r.get("content"))]).lower(), axis=1)
        df["matched_terms"] = df["_blob"].apply(lambda t: extract_matched_terms(t, primary_terms))
        df["match_count"] = df["matched_terms"].apply(lambda lst: len(lst) if isinstance(lst, list) else 0)
    else:
        df["matched_terms"] = [[] for _ in range(len(df))]
        df["match_count"] = 0

    # Basic hygiene
    df["author"] = df["author"].fillna("").astype(str).str.strip()
    df["source"] = df["source"].fillna("").astype(str).str.strip()

    # Drop hard-blocked authors early
    df = df[~df["author"].apply(is_blocked_author)].copy()

    df["is_person"] = df["author"].apply(is_likely_person)
    df["is_wire_pr"] = df.apply(lambda r: classify_wire_pr(_safe_str(r.get("source")), _safe_str(r.get("author")), _safe_str(r.get("title"))), axis=1)

    df = df.dropna(subset=["url"]).drop_duplicates(subset=["url"]).copy()

    # Sort with relevance first
    df = df.sort_values(["match_count", "publishedAt"], ascending=[False, False])

    return df

def _aggregate_entities(df_articles: pd.DataFrame, keep_person: bool) -> pd.DataFrame:
    if df_articles.empty:
        return pd.DataFrame(columns=["author", "source", "articles", "last_seen", "matched_terms", "evidence", "apis"])

    d = df_articles.copy()
    d["author"] = d["author"].fillna("").astype(str).str.strip()
    d = d[d["author"] != ""].copy()

    if keep_person:
        d = d[d["is_person"] == True].copy()
    else:
        d = d[d["is_person"] == False].copy()

    if d.empty:
        return pd.DataFrame(columns=["author", "source", "articles", "last_seen", "matched_terms", "evidence", "apis"])

    primary_terms = st.session_state.last_query_terms or []

    def _top_terms(series: pd.Series, n: int = 5) -> List[str]:
        counts: Dict[str, int] = {}
        for lst in series.dropna():
            for t in (lst or []):
                counts[t] = counts.get(t, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]]

    def _evidence_titles(group: pd.DataFrame, n: int = 2) -> str:
        g = group.copy()
        g["publishedAt"] = pd.to_datetime(g["publishedAt"], errors="coerce", utc=True)
        g = g.sort_values(["match_count", "publishedAt"], ascending=[False, False])
        titles = []
        for _, row in g.head(8).iterrows():
            title = _safe_str(row.get("title"))
            terms = row.get("matched_terms") or primary_terms
            terms = [t for t in terms if t]
            titles.append(highlight_terms(title, terms, max_len=140))
            if len(titles) >= n:
                break
        return " | ".join([t for t in titles if t])

    def _apis_list(group: pd.DataFrame) -> str:
        vals = sorted({str(x) for x in group["source_api"].dropna().tolist() if str(x)})
        return ", ".join(vals)

    grouped = d.groupby(["author", "source"], dropna=False).apply(
        lambda g: pd.Series({
            "articles": int(g["url"].count()),
            "last_seen": pd.to_datetime(g["publishedAt"], errors="coerce", utc=True).max(),
            "matched_terms": ", ".join(_top_terms(g["matched_terms"])),
            "evidence": _evidence_titles(g),
            "apis": _apis_list(g),
        })
    ).reset_index()

    return grouped.sort_values(["articles", "last_seen"], ascending=[False, False])

def _ensure_results():
    if not st.session_state.search_clicked:
        return

    st.session_state.last_query_terms = _build_query_terms()
    df = _load_articles()

    df_wires = df[df["is_wire_pr"] == True].copy() if not df.empty else pd.DataFrame()
    df_main = df[df["is_wire_pr"] == False].copy() if (st.session_state.separate_wires and not df.empty) else df

    if st.session_state.hide_non_person and not df_main.empty:
        df_main = df_main[df_main["is_person"] == True].copy()

    st.session_state.last_results_articles = df
    st.session_state.last_results_reporters = _aggregate_entities(df_main, keep_person=True)
    st.session_state.last_results_wires = _aggregate_entities(df_wires, keep_person=False)
    st.session_state.search_clicked = False

_ensure_results()

df_articles: Optional[pd.DataFrame] = st.session_state.last_results_articles
df_reporters: Optional[pd.DataFrame] = st.session_state.last_results_reporters
df_wires: Optional[pd.DataFrame] = st.session_state.last_results_wires

with tab_reporter:
    st.subheader("Reporters")
    st.caption("Now includes an `apis` column so you can see whether a row came from Perigon or NewsAPI.")
    if df_reporters is None:
        st.info("Enter keywords in the sidebar and click Search.")
    else:
        st.dataframe(df_reporters, use_container_width=True)

with tab_wires:
    st.subheader("Wires / PR / Organizations")
    st.caption("Separated from reporters to avoid drowning out real names.")
    if df_wires is None:
        st.info("Run a search to populate this tab.")
    else:
        st.dataframe(df_wires, use_container_width=True)

with tab_articles:
    st.subheader("Articles")
    st.caption("Includes `source_api` so you can see which API returned each article.")
    if df_articles is None:
        st.info("Enter keywords in the sidebar and click Search.")
    else:
        view = df_articles.copy()
        view["topics"] = view["topics_norm"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
        view["matched_terms"] = view["matched_terms"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
        cols = ["source_api", "source", "author", "title", "matched_terms", "publishedAt", "url", "topics"]
        for c in cols:
            if c not in view.columns:
                view[c] = ""
        st.dataframe(view[cols], use_container_width=True)

st.caption("Hard blocklist enabled (Option B). Add more author strings in BLOCKED_AUTHORS as you encounter them.")
