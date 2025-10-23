import os
import re
from dateutil import parser as dateparser

import streamlit as st
import pandas as pd
import requests

# ===== Config =====
st.set_page_config(page_title="Reporter Finder (Weighted + Perigon)", page_icon="📰", layout="wide")

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
TOP_TIER_WEIGHT = 2
DEFAULT_WEIGHT = 1

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

# ---- NewsAPI fetch (normalized) ----
def get_newsapi_articles(topic: str, max_results: int, sort_by: str):
    if not NEWS_API_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {"q": topic, "apiKey": NEWS_API_KEY, "language": "en", "pageSize": max_results, "sortBy": sort_by}
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 401:
            return []
        r.raise_for_status()
    except requests.RequestException:
        return []
    data = r.json() or {}
    items = data.get("articles", []) or []
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

# ---- Perigon fetch (normalized) ----
def get_perigon_articles(topic: str, max_results: int, sort_by: str):
    if not PERIGON_API_KEY:
        return []
    url = "https://api.goperigon.com/v1/all"
    perigon_sort = "relevance" if sort_by == "relevancy" else "date"
    params = {
        "q": topic,
        "apiKey": PERIGON_API_KEY,
        "size": max_results,
        "sortBy": perigon_sort,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 401:
            return []
        r.raise_for_status()
    except requests.RequestException:
        return []
    data = r.json() or {}
    items = data.get("articles") or data.get("data") or []
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

# ---- Unified fetch & dedupe ----
def search_articles(topic: str, max_results: int, sort_by: str):
    newsapi_list = get_newsapi_articles(topic, max_results, sort_by)
    perigon_list = get_perigon_articles(topic, max_results, sort_by)
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
    try:
        r = requests.get(url, params=params, timeout=20)
        emails = r.json().get("data", {}).get("emails", [])
        return emails[0].get("value") if emails else None
    except Exception:
        return None

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

st.title("📰 Reporter Finder — Weighted by Outlet Prominence (NewsAPI + Perigon)")
st.caption("Search by topic; results aggregate reporters; sources fetched in parallel from NewsAPI and Perigon.")

if not login():
    st.stop()

with st.sidebar:
    st.header("Search Settings")
    topic = st.text_input("Topic", placeholder="e.g., AI in healthcare")
    max_results = st.slider("Articles to fetch (per source)", 20, 200, 100)
    sort_by = st.selectbox("Sort articles by", ["relevancy", "publishedAt", "popularity"], index=1)
    enrich_emails = st.checkbox("Enrich with emails (Hunter.io)", value=bool(HUNTER_API_KEY))
    run = st.button("Search & Aggregate Reporters")

if run:
    if not topic.strip():
        st.error("Please enter a topic.")
        st.stop()

    with st.spinner("Fetching from NewsAPI + Perigon and aggregating by reporter…"):
        articles = search_articles(topic, max_results, sort_by)

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
            }
        reporters[author]["outlets"].add(outlet)
        reporters[author]["articles"].append({
            "title": title,
            "url": url,
            "outlet": outlet,
            "published": published
        })

    rows = []
    for author, info in reporters.items():
        articles_list = info["articles"]
        count = len(articles_list)
        weights = [outlet_weight_for(o) for o in info["outlets"] if o]
        outlet_multiplier = max(weights) if weights else DEFAULT_WEIGHT
        score = count * outlet_multiplier
        try:
            articles_sorted = sorted(articles_list, key=lambda x: dateparser.parse(x.get("published") or ""), reverse=True)
        except Exception:
            articles_sorted = articles_list
        top_articles = articles_sorted[:5]
        outlets_str = ", ".join(sorted({o for o in info["outlets"] if o}))
        email = ""
        if enrich_emails and top_articles:
            domain = extract_domain(top_articles[0].get("url") or "") or ""
            if domain:
                email = hunter_email(domain) or ""
        rows.append({
            "Reporter": author,
            "Outlets": outlets_str,
            "ArticlesMatched": count,
            "Score": score,
            "TopArticles": top_articles,
            "Email": email,
        })

    if not rows:
        st.warning("No reporters found.")
        st.stop()

    df = pd.DataFrame(rows).sort_values(by=["Score", "ArticlesMatched"], ascending=False)

    st.success(f"Found {len(df)} reporters. (Merged from NewsAPI + Perigon)")
    st.markdown("---")
    for _, r in df.reset_index(drop=True).iterrows():
        with st.container():
            cols = st.columns([3, 3, 1, 1, 1])
            cols[0].markdown(f"**{r['Reporter']}**")
            cols[1].write(r['Outlets'])
            cols[2].write(int(r['ArticlesMatched']))
            cols[3].write(float(r['Score']))
            cols[4].write(r['Email'] or "")
            with st.expander("Recent articles (click to open)"):
                for art in r['TopArticles']:
                    title = art.get('title') or art.get('url')
                    url = art.get('url')
                    pub = art.get('published') or ''
                    st.markdown(f"- [{title}]({url}) <small>({pub})</small>", unsafe_allow_html=True)

    # CSV export
    csv_rows = [{
        "Reporter": r["Reporter"],
        "Outlets": r["Outlets"],
        "ArticlesMatched": r["ArticlesMatched"],
        "Score": r["Score"],
        "Email": r["Email"],
    } for r in rows]
    csv_df = pd.DataFrame(csv_rows).sort_values(by=["Score", "ArticlesMatched"], ascending=False)
    csv = csv_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download reporters CSV", data=csv, file_name="reporters_weighted_merged.csv", mime="text/csv")

st.markdown("<small>Use responsibly. Verify contacts before outreach.</small>", unsafe_allow_html=True)
