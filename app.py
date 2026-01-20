import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

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

# Optional CSS override (safe if missing)
load_css("assets/custom.css")

NEWSAPI_FREE_MAX_DAYS = 29  # conservative for free/dev plans


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
# Exact matches (lowercased, stripped).
BLOCKED_AUTHORS = {
    "scienmag",
    "globe newswire",
    "globenewswire",
    "newsfinal journal",
}

# Contains-based blocks for common wire-ish bylines
BLOCKED_AUTHOR_CONTAINS = (
    "globenewswire",
    "prnewswire",
    "businesswire",
)

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _safe_str(x: Any) -> str:
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
        # Single tokens are ambiguous, but allow capitalized alpha tokens
        return tokens[0].isalpha() and tokens[0][0].isupper() and len(tokens[0]) >= 3

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
    hits: List[str] = []
    for term in terms:
        if term and term.lower() in t:
            hits.append(term.lower())
    # de-dupe preserving order
    seen: set[str] = set()
    out: List[str] = []
    for h in hits:
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
    # NewsAPI temporarily disabled by default (debugging + cleaner authors)
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
            suggestions=suggested,
            maxtags=12,
            key="topics_tags",
        )
    except Exception:
        used_fallback = True
        topics_text = st.text_input(
            "Topics / beats (optional)",
            value=",".join(st.session_state.topics) if st.session_state.topics else "",
            placeholder="e.g., healthcare, insurance, biotech",
        )
        topics = parse_keywords(topics_text)

    st.session_state.topics = normalize_topics(topics)

    st.caption(
        "Topics are used as metadata **when available** (Perigon taxonomies/topics), "
        "otherwise they’re treated as extra keyword hints."
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
        help="NewsAPI free plan is often limited to the last ~30 days on /everything.",
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
        help="Hides desks, organizations, many wires/PR, and other non-person bylines.",
    )
    st.session_state.separate_wires = st.checkbox(
        "Separate wire / PR sources into their own tab",
        value=bool(st.session_state.separate_wires),
        help="Keeps press releases and wire content out of the Reporters tab (still accessible).",
    )

    st.divider()
    st.caption("Sources (NewsAPI is off by default)")
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