import os
import re
from dateutil import parser as dateparser

import streamlit as st
import pandas as pd
import requests

# ===== Config =====
st.set_page_config(page_title="Reporter Finder (Weighted)", page_icon="📰", layout="wide")

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
HUNTER_API_KEY = st.secrets.get("HUNTER_API_KEY", os.getenv("HUNTER_API_KEY", ""))
APP_USERNAME = st.secrets.get("APP_USERNAME", os.getenv("APP_USERNAME", ""))
APP_PASSWORD = st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", ""))

# ===== Helpers =====
def extract_domain(url: str):
    m = re.match(r"https?://([^/]+)/?", url or "")
    return m.group(1) if m else None

def search_news(topic: str, max_results: int, sort_by: str):
    if not NEWS_API_KEY:
        st.error("Missing NEWS_API_KEY — please add it to Streamlit secrets.")
        st.stop()
    url = "https://newsapi.org/v2/everything"
    params = {"q": topic, "apiKey": NEWS_API_KEY, "language": "en", "pageSize": max_results, "sortBy": sort_by}
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 401:
            st.error("NewsAPI authentication failed — check your API key.")
            st.stop()
        r.raise_for_status()
    except requests.RequestException as e:
        st.error(f"News search failed: {e}")
        st.stop()
    return r.json().get("articles", [])

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
    # Normalize a bit: some outlets in API responses include suffixes, make a simple match
    if not outlet_name:
        return DEFAULT_WEIGHT
    cleaned = outlet_name.strip()
    if cleaned in TOP_TIER_OUTLETS:
        return TOP_TIER_WEIGHT
    # try a looser comparison (case-insensitive)
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

st.title("📰 Reporter Finder — Weighted by Outlet Prominence")
st.caption("Search by topic; results aggregate reporters and weight scores by outlet prominence.")

if not login():
    st.stop()

with st.sidebar:
    st.header("Search Settings")
    topic = st.text_input("Topic", placeholder="e.g., AI in healthcare")
    max_results = st.slider("Articles to fetch", 20, 200, 100)
    sort_by = st.selectbox("Sort articles by (NewsAPI)", ["relevancy", "publishedAt", "popularity"], index=1)
    enrich_emails = st.checkbox("Enrich with emails (Hunter.io)", value=bool(HUNTER_API_KEY))
    run = st.button("Search & Aggregate Reporters")

if run:
    if not topic.strip():
        st.error("Please enter a topic.")
        st.stop()

    with st.spinner("Searching news and aggregating by reporter…"):
        articles = search_news(topic, max_results, sort_by)

    # Aggregate articles by author
    reporters = {}
    for a in articles:
        author = (a.get("author") or "").strip()
        title = (a.get("title") or "").strip()
        url = a.get("url")
        outlet = (a.get("source", {}).get("name") or "").strip()
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

    # Build scored list
    rows = []
    for author, info in reporters.items():
        articles_list = info["articles"]
        count = len(articles_list)
        # compute outlet-weighted multiplier as max of outlet weights for that author
        weights = [outlet_weight_for(o) for o in info["outlets"] if o]
        # if author has multiple outlets, use max weight to favor articles published in top outlets
        outlet_multiplier = max(weights) if weights else DEFAULT_WEIGHT
        score = count * outlet_multiplier
        # sort author's articles by published date desc and keep top 5
        try:
            articles_sorted = sorted(articles_list, key=lambda x: dateparser.parse(x.get("published") or ""), reverse=True)
        except Exception:
            articles_sorted = articles_list
        top_articles = articles_sorted[:5]
        outlets_str = ", ".join(sorted({o for o in info["outlets"] if o}))
        # optional email lookup (try to grab domain from first article)
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

    st.success(f"Found {len(df)} reporters. Sorted by score (article_count × outlet weight).")

    # Display table (Reporter | Outlets | #Articles | Score | Email) and expanders for each reporter
    st.markdown("---")
    for idx, r in df.reset_index(drop=True).iterrows():
        with st.container():
            cols = st.columns([3, 3, 1, 1, 1])
            cols[0].markdown(f"**{r['Reporter']}**")
            cols[1].write(r['Outlets'])
            cols[2].write(int(r['ArticlesMatched']))
            cols[3].write(float(r['Score']))
            if r['Email']:
                cols[4].write(r['Email'])
            else:
                cols[4].write("")
            with st.expander("Recent articles (click to open)"):
                for art in r['TopArticles']:
                    title = art.get('title') or art.get('url')
                    url = art.get('url')
                    pub = art.get('published') or ''
                    # render as a markdown hyperlink
                    st.markdown(f"- [{title}]({url}) <small>({pub})</small>", unsafe_allow_html=True)

    # CSV download
    csv_rows = []
    for r in rows:
        csv_rows.append({
            'Reporter': r['Reporter'],
            'Outlets': r['Outlets'],
            'ArticlesMatched': r['ArticlesMatched'],
            'Score': r['Score'],
            'Email': r['Email'],
        })
    csv_df = pd.DataFrame(csv_rows).sort_values(by=['Score', 'ArticlesMatched'], ascending=False)
    csv = csv_df.to_csv(index=False).encode('utf-8')
    st.download_button('📥 Download reporters CSV', data=csv, file_name='reporters_weighted.csv', mime='text/csv')

st.markdown("<small>Use responsibly. Verify contacts before outreach.</small>", unsafe_allow_html=True)
