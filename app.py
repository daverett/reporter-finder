import os
import re
from dateutil import parser as dateparser

import streamlit as st
import pandas as pd
import requests

# ===== Config =====
st.set_page_config(page_title="Reporter Finder", page_icon="📰", layout="wide")

# ===== Secrets =====
try:
    NEWS_API_KEY = st.secrets["NEWS_API_KEY"]
except KeyError:
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

HUNTER_API_KEY = st.secrets.get("HUNTER_API_KEY", os.getenv("HUNTER_API_KEY", ""))
APP_USERNAME = st.secrets.get("APP_USERNAME", os.getenv("APP_USERNAME", ""))
APP_PASSWORD = st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", ""))

# ===== Simple Auth =====
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
    except:
        return None

# ===== UI =====
st.title("📰 Reporter Finder")
st.caption("Find journalists writing about your topic — with optional contact emails from Hunter.io.")

if not login():
    st.stop()

with st.sidebar:
    st.header("Search Settings")
    topic = st.text_input("Topic", placeholder="e.g., AI in healthcare")
    max_results = st.slider("Articles to fetch", 10, 100, 50)
    sort_by = st.selectbox("Sort by", ["relevancy", "publishedAt", "popularity"], index=1)
    enrich_emails = st.checkbox("Enrich with emails (Hunter.io)", value=bool(HUNTER_API_KEY))
    run = st.button("Search")

if run:
    if not topic.strip():
        st.error("Please enter a topic.")
        st.stop()

    with st.spinner("Searching news…"):
        articles = search_news(topic, max_results, sort_by)

    rows = []
    seen = set()

    for a in articles:
        author = (a.get("author") or "").strip()
        title = (a.get("title") or "").strip()
        url = a.get("url")
        outlet = (a.get("source", {}).get("name") or "").strip()
        published = a.get("publishedAt")

        if not author or not url:
            continue
        if (author, url) in seen:
            continue
        seen.add((author, url))

        domain = extract_domain(url) or ""
        email = hunter_email(domain) if enrich_emails and domain else None

        try:
            dt = dateparser.parse(published)
            published_fmt = dt.strftime("%Y-%m-%d %H:%M") if dt else published
        except:
            published_fmt = published

        rows.append({
            "Reporter": author,
            "Outlet": outlet,
            "Article": f"[{title}]({url})",
            "Published": published_fmt,
            "Email": email or "",
        })

    if not rows:
        st.warning("No reporters found.")
        st.stop()

    df = pd.DataFrame(rows).sort_values("Published", ascending=False)
    st.success(f"Found {len(df)} entries.")
    st.dataframe(df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", csv, "reporters_list.csv", "text/csv")

st.markdown("<small>Use responsibly. Verify contacts before outreach.</small>", unsafe_allow_html=True)
