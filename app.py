import os
import re
from datetime import datetime, timedelta, date
from dateutil import parser as dateparser

import streamlit as st
import pandas as pd
import requests
import math

# ===== Config =====
st.set_page_config(page_title="Reporter Finder — Articles & Reporters", page_icon="📰", layout="wide")

# ===== Top-tier outlets (starter set) =====
TOP_TIER_OUTLETS = {
    "The New York Times",
    "The Washington Post",
    "Reuters",
    "Bloomberg",
    "BBC News",
    "CNN",
    "The Wall Street Journal",
    "Financial Times",
    "The Guardian",
    "Politico",
    "NPR",
    "Associated Press",
    "Los Angeles Times",
    "TIME",
    "Forbes",
    "Fortune",
    "Vox",
    "Axios",
    "The Atlantic",
    "NBC News",
}
TOP_TIER_WEIGHT = 2.0
DEFAULT_WEIGHT = 1.0

# ===== Secrets =====
try:
    NEWS_API_KEY = st.secrets["NEWS_API_KEY"]
except Exception:
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
try:
    PERIGON_API_KEY = st.secrets["PERIGON_API_KEY"]
except Exception:
    PERIGON_API_KEY = os.getenv("PERIGON_API_KEY", "")
HUNTER_API_KEY = st.secrets.get("HUNTER_API_KEY", os.getenv("HUNTER_API_KEY", ""))
APP_USERNAME = st.secrets.get("APP_USERNAME", os.getenv("APP_USERNAME", ""))
APP_PASSWORD = st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", ""))

# ===== Helpers =====
def extract_domain(url: str):
    m = re.match(r"https?://([^/]+)/?", url or "")
    return m.group(1) if m else None

def iso_date(d: date):
    if not d:
        return None
    return datetime(d.year, d.month, d.day).isoformat()

# ===== Caching =====
@st.cache_data(show_spinner=False, ttl=300)
def cached_get(url, params, headers=None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else r.text)
    except Exception as e:
        return -1, {"error": str(e)}

# ---- NewsAPI fetch (normalized) ----
def get_newsapi_articles(topic: str, max_results: int, sort_by: str, d_from: str=None, d_to: str=None):
    if not NEWS_API_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {"q": topic, "apiKey": NEWS_API_KEY, "language": "en", "pageSize": max_results, "sortBy": sort_by}
    if d_from:
        params["from"] = d_from
    if d_to:
        params["to"] = d_to
    code, data = cached_get(url, params)
    if code != 200:
        return []
    items = (data or {}).get("articles", []) or []
    results = []
    for it in items:
        title = (it.get("title") or "").strip()
        url_ = it.get("url") or ""
        author = (it.get("author") or "").strip()
        source = (it.get("source") or {}).get("name") or ""
        published = it.get("publishedAt") or ""
        if not title or not url_:
            continue
        results.append({
            "title": title,
            "url": url_,
            "source": source,
            "author": author,
            "publishedAt": published,
        })
    return results

# ---- Perigon "all" fetch (normalized) ----
def get_perigon_articles(topic: str, max_results: int, sort_by: str, d_from: str=None, d_to: str=None):
    if not PERIGON_API_KEY:
        return []
    url = "https://api.goperigon.com/v1/all"
    perigon_sort = "relevance" if sort_by == "relevancy" else "date"
    params = {"q": topic, "apiKey": PERIGON_API_KEY, "size": max_results, "sortBy": perigon_sort}
    # Perigon date params commonly accept 'from'/'to' in ISO; if unsupported, API will ignore.
    if d_from:
        params["from"] = d_from
    if d_to:
        params["to"] = d_to
    code, data = cached_get(url, params)
    if code != 200:
        return []
    items = (data or {}).get("articles") or (data or {}).get("data") or []
    results = []
    for it in items:
        title = (it.get("title") or it.get("headline") or "").strip()
        url_ = it.get("url") or it.get("link") or ""
        # source normalization
        source_name = ""
        src = it.get("source")
        if isinstance(src, dict):
            source_name = (src.get("name") or src.get("domain") or "").strip()
        elif isinstance(src, str):
            source_name = src.strip()
        # author normalization
        author = ""
        if isinstance(it.get("author"), str):
            author = it["author"].strip()
        elif isinstance(it.get("authors"), list) and it["authors"]:
            author = ", ".join([a for a in it["authors"] if isinstance(a, str)])[:200]
        published = it.get("publishedAt") or it.get("pubDate") or it.get("date") or ""
        if not title or not url_:
            continue
        results.append({
            "title": title,
            "url": url_,
            "source": source_name,
            "author": author,
            "publishedAt": published,
        })
    return results

# ---- Perigon Journalists search (enrichment, cached) ----
@st.cache_data(show_spinner=False, ttl=3600)
def perigon_find_journalist(author_name: str, topic_query: str = ""):
    if not PERIGON_API_KEY or not author_name:
        return {}
    url = "https://api.goperigon.com/v1/journalists"
    params = {"apiKey": PERIGON_API_KEY, "q": author_name, "size": 1}
    if topic_query:
        params["topic"] = topic_query
    code, payload = cached_get(url, params)
    if code != 200 or not isinstance(payload, dict):
        return {}
    items = payload.get("journalists") or payload.get("data") or payload.get("results") or []
    if not items:
        return {}
    j = items[0]
    profile = {
        "name": j.get("name") or author_name,
        "title": j.get("title") or j.get("role") or "",
        "bio": j.get("bio") or "",
        "twitter": j.get("twitter") or j.get("twitter_handle") or "",
        "linkedin": j.get("linkedin") or j.get("linkedin_url") or "",
        "location": j.get("location") or "",
        "topics": j.get("topics") or j.get("top_topics") or [],
        "sources": j.get("top_sources") or j.get("sources") or [],
    }
    if isinstance(profile["topics"], list):
        profile["topics"] = [str(t) for t in profile["topics"]]
    if isinstance(profile["sources"], list):
        profile["sources"] = [str(s) for s in profile["sources"]]
    return profile

# ---- Unified fetch & dedupe ----
def search_articles(topic: str, max_results: int, sort_by: str, d_from: str=None, d_to: str=None):
    newsapi_list = get_newsapi_articles(topic, max_results, sort_by, d_from, d_to)
    perigon_list = get_perigon_articles(topic, max_results, sort_by, d_from, d_to)
    combined = []
    seen = set()
    for src_list in (newsapi_list, perigon_list):
        for a in src_list:
            url = (a.get("url") or "").strip().lower()
            if not url or url in seen:
                continue
            seen.add(url)
            combined.append({
                "title": a.get("title", "").strip(),
                "url": a.get("url", "").strip(),
                "source": a.get("source", "").strip(),
                "author": a.get("author", "").strip(),
                "publishedAt": a.get("publishedAt", ""),
            })
    return combined

def hunter_email(domain: str):
    if not HUNTER_API_KEY:
        return None
    url = "https://api.hunter.io/v2/domain-search"
    params = {"domain": domain, "api_key": HUNTER_API_KEY, "limit": 1}
    code, data = cached_get(url, params)
    if code != 200 or not isinstance(data, dict):
        return None
    emails = data.get("data", {}).get("emails", [])
    return emails[0].get("value") if emails else None

def outlet_weight_for(outlet_name: str):
    if not outlet_name:
        return DEFAULT_WEIGHT
    cleaned = outlet_name.strip()
    if cleaned in TOP_TIER_OUTLETS:
        return TOP_TIER_WEIGHT
    for t in TOP_TIER_OUTLETS:
        if cleaned.lower() == t.lower():
            return TOP_TIER_WEIGHT
    return DEFAULT_WEIGHT

# ===== Scoring =====
def recency_weight(published_iso: str, half_life_days: float = 30.0):
    if not published_iso:
        return 1.0
    try:
        dt = dateparser.parse(published_iso)
        if not dt:
            return 1.0
        days_old = max(0.0, (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() / 86400.0)
        # Exponential decay: weight halves every 'half_life_days'
        return pow(0.5, days_old / half_life_days)
    except Exception:
        return 1.0

def compute_score(articles_list, outlets_set, method: str):
    count = len(articles_list)
    prominence = max([outlet_weight_for(o) for o in outlets_set if o] or [DEFAULT_WEIGHT])
    if method == "Frequency only":
        return float(count)
    if method == "Prominence-weighted":
        return float(count) * prominence
    if method == "Recency-weighted":
        # sum of recency weights over articles
        return sum(recency_weight(a.get("published")) for a in articles_list)
    if method == "Hybrid (Freq × Prominence × Recency)":
        rec = sum(recency_weight(a.get("published")) for a in articles_list)
        # normalize recency by number of articles to avoid double-counting when multiplying
        rec_norm = rec / max(1.0, count)
        return float(count) * prominence * rec_norm
    return float(count)

# ===== UI / Auth =====
def login():
    if not APP_USERNAME or not APP_PASSWORD:
        return True
    with st.sidebar:
        st.subheader("🔐 Login")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Sign in") and u == APP_USERNAME and p == APP_PASSWORD:
            st.session_state["auth"] = True
    return st.session_state.get("auth", False)

st.title("📰 Reporter Finder — Articles & Reporters (NewsAPI + Perigon)")
st.caption("Date filters, caching, and scoring controls included. Optional Hunter.io emails and Perigon journalist enrichment.")

if not login():
    st.stop()

with st.sidebar:
    st.header("Search Settings")
    topic = st.text_input("Topic", placeholder="e.g., AI in healthcare")
    max_results = st.slider("Articles to fetch (per source)", 20, 200, 100)
    sort_by = st.selectbox("Sort articles by", ["relevancy", "publishedAt", "popularity"], index=1)
    # Date range (default last 30 days)
    today = datetime.utcnow().date()
    default_from = today - timedelta(days=30)
    d_range = st.date_input("Date range", (default_from, today))
    if isinstance(d_range, tuple) and len(d_range) == 2:
        d_from_val, d_to_val = d_range
    else:
        d_from_val, d_to_val = default_from, today
    d_from_iso = iso_date(d_from_val)
    # Add one day to 'to' to be inclusive
    d_to_iso = iso_date(d_to_val + timedelta(days=1))

    enrich_emails = st.checkbox("Enrich with emails (Hunter.io)", value=bool(HUNTER_API_KEY))
    enrich_journalists = st.checkbox("Enrich reporter profiles (Perigon)", value=bool(PERIGON_API_KEY))
    scoring_method = st.selectbox("Scoring method", ["Frequency only", "Prominence-weighted", "Recency-weighted", "Hybrid (Freq × Prominence × Recency)"], index=1)
    run = st.button("Search")

if run:
    if not topic.strip():
        st.error("Please enter a topic.")
        st.stop()

    with st.spinner("Fetching from NewsAPI + Perigon…"):
        articles = search_articles(topic, max_results, sort_by, d_from_iso, d_to_iso)

    tab_articles, tab_reporters = st.tabs(["📰 Articles", "🧑‍💼 Reporters"])

    # === Articles Tab ===
    with tab_articles:
        if not articles:
            st.warning("No articles found.")
        else:
            art_rows = []
            for a in articles:
                try:
                    dt = dateparser.parse(a.get("publishedAt") or "")
                    published_fmt = dt.strftime("%Y-%m-%d %H:%M") if dt else a.get("publishedAt") or ""
                except Exception:
                    published_fmt = a.get("publishedAt") or ""
                art_rows.append({
                    "Title": f"[{a.get('title')}]({a.get('url')})",
                    "Outlet": a.get("source"),
                    "Author": a.get("author"),
                    "Published": published_fmt,
                })
            art_df = pd.DataFrame(art_rows)
            st.dataframe(art_df, use_container_width=True, hide_index=True)
            csv_articles = pd.DataFrame([
                {"Title": a["title"], "URL": a["url"], "Outlet": a["source"], "Author": a["author"], "PublishedAt": a["publishedAt"]}
                for a in articles
            ]).to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download articles CSV", data=csv_articles, file_name="articles.csv", mime="text/csv")

    # === Reporters Tab ===
    with tab_reporters:
        # Aggregate by reporter
        reporters = {}
        for a in articles:
            author = (a.get("author") or "").strip()
            title = (a.get("title") or "").strip()
            url = a.get("url")
            outlet = (a.get("source") or "").strip()
            published = a.get("publishedAt")

            if not author or not url:
                continue

            if author not in reporters:
                reporters[author] = {
                    "author": author,
                    "outlets": set(),
                    "articles": [],
                    "profile": {},  # Perigon journalist enrichment
                }
            reporters[author]["outlets"].add(outlet)
            reporters[author]["articles"].append({
                "title": title,
                "url": url,
                "outlet": outlet,
                "published": published
            })

        # Build rows with weighting + optional enrichment
        rows = []
        for author, info in reporters.items():
            articles_list = info["articles"]
            outlets_set = info["outlets"]
            score = compute_score(articles_list, outlets_set, scoring_method)
            try:
                articles_sorted = sorted(articles_list, key=lambda x: dateparser.parse(x.get("published") or ""), reverse=True)
            except Exception:
                articles_sorted = articles_list
            top_articles = articles_sorted[:5]
            outlets_str = ", ".join(sorted({o for o in outlets_set if o}))
            email = ""
            if enrich_emails and top_articles:
                domain = extract_domain(top_articles[0].get("url") or "") or ""
                if domain:
                    email = hunter_email(domain) or ""
            profile = {}
            if enrich_journalists:
                profile = perigon_find_journalist(author, topic_query=topic) or {}
            rows.append({
                "Reporter": author,
                "Outlets": outlets_str,
                "ArticlesMatched": len(articles_list),
                "Score": score,
                "TopArticles": top_articles,
                "Email": email,
                "Profile": profile,
            })

        if not rows:
            st.warning("No reporters found.")
        else:
            df = pd.DataFrame(rows).sort_values(by=["Score", "ArticlesMatched"], ascending=False)
            st.success(f"Found {len(df)} reporters (merged from NewsAPI + Perigon). Scoring: {scoring_method}.")
            st.markdown("---")
            for _, r in df.reset_index(drop=True).iterrows():
                with st.container():
                    cols = st.columns([3, 3, 1, 1, 1])
                    header = r['Reporter']
                    title_suffix = ""
                    prof = r.get("Profile") or {}
                    if prof.get("title"):
                        title_suffix = f" — {prof['title']}"
                    cols[0].markdown(f"**{header}**{title_suffix}")
                    cols[1].write(r['Outlets'])
                    cols[2].write(int(r['ArticlesMatched']))
                    cols[3].write(round(float(r['Score']), 3))
                    cols[4].write(r['Email'] or "")

                    with st.expander("Recent articles (click to open)"):
                        for art in r['TopArticles']:
                            title = art.get('title') or art.get('url')
                            url = art.get('url')
                            pub = art.get('published') or ''
                            st.markdown(f"- [{title}]({url}) <small>({pub})</small>", unsafe_allow_html=True)

                    if prof:
                        with st.expander("Journalist profile (Perigon)"):
                            if prof.get("bio"):
                                st.markdown(f"**Bio:** {prof['bio']}")
                            meta_cols = st.columns(3)
                            meta_cols[0].markdown(f"**Location:** {prof.get('location','')}")
                            meta_cols[1].markdown(f"**Twitter:** {prof.get('twitter','')}")
                            meta_cols[2].markdown(f"**LinkedIn:** {prof.get('linkedin','')}")
                            topics = prof.get("topics") or []
                            sources = prof.get("sources") or []
                            if topics:
                                st.markdown("**Top topics:** " + ", ".join(topics[:10]))
                            if sources:
                                st.markdown("**Top sources:** " + ", ".join(sources[:10]))

            # CSV export (reporter-level)
            csv_rows = [{
                "Reporter": r["Reporter"],
                "Outlets": r["Outlets"],
                "ArticlesMatched": r["ArticlesMatched"],
                "Score": r["Score"],
                "Email": r["Email"],
                "ProfileTitle": (r.get("Profile") or {}).get("title",""),
                "ProfileTopics": ", ".join((r.get("Profile") or {}).get("topics", [])[:10]),
            } for r in rows]
            csv_df = pd.DataFrame(csv_rows).sort_values(by=["Score", "ArticlesMatched"], ascending=False)
            csv = csv_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download reporters CSV", data=csv, file_name="reporters_scored.csv", mime="text/csv")

st.markdown("<small>Use responsibly. Verify contacts before outreach and follow each API’s terms.</small>", unsafe_allow_html=True)
