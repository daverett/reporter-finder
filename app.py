
import os
import re
from datetime import datetime, timedelta, date
import streamlit as st
import pandas as pd
import requests
from dateutil import parser as dateparser

# ====================
# CONFIG & THEME
# ====================
st.set_page_config(page_title="Reporter Finder — Articles & Reporters", page_icon="📰", layout="wide")

# Initialize session state
if "auth" not in st.session_state:
    st.session_state.auth = False
if "user" not in st.session_state:
    st.session_state.user = None

# Palette
PRIMARY = "#055258"    # headings
ACCENT = "#35ce8d"     # primary accent
SAGE = "#6ba292"       # secondary accent
SOFT_WHITE = "#e5e0e0" # background
DARK = "#303030"       # text

THEME_CSS = f'''
<style>
  :root {{
    --primary: {PRIMARY};
    --accent: {ACCENT};
    --sage: {SAGE};
    --bg: {SOFT_WHITE};
    --text: {DARK};
  }}
  .stApp {{
    background: var(--bg);
    color: var(--text);
  }}
  h1, h2, h3, h4, h5, h6 {{ color: var(--primary); }}
  .app-header {{
    background: linear-gradient(to right, rgba(5,82,88,0.12), rgba(53,206,141,0.12));
    border: 1px solid rgba(5,82,88,0.15);
    padding: 14px 18px;
    border-radius: 14px;
    margin-bottom: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }}
  .app-header h1 {{ margin: 0; font-size: 1.6rem; line-height: 1.2; }}
  .app-sub {{ margin-top: 4px; color: var(--text); opacity: 0.85; font-size: 0.95rem; }}
  .card {{
    background: #ffffff20;
    border: 1px solid rgba(0,0,0,0.05);
    border-radius: 16px;
    padding: 14px;
    margin: 10px 0 16px 0;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08);
  }}
  .badge {{
    display: inline-block; padding: 4px 8px; border-radius: 999px;
    font-size: 0.8rem; font-weight: 600; margin-right: 6px; margin-top: 6px;
  }}
  .badge-score-low {{ background: rgba(107,162,146,0.32); color: var(--text); border: 1px solid rgba(107,162,146,0.5); }}
  .badge-score-mid {{ background: rgba(53,206,141,0.28); color: var(--text); border: 1px solid rgba(53,206,141,0.5); }}
  .badge-score-high {{ background: rgba(5,82,88,0.28); color: #fff; border: 1px solid rgba(5,82,88,0.6); }}
  .badge-score-top {{ background: rgba(48,48,48,0.85); color: #fff; border: 1px solid rgba(48,48,48,0.9); }}
  .stTabs [role="tablist"] {{ gap: 6px; }}
  .stTabs [role="tab"] {{
    border: 1px solid rgba(0,0,0,0.08); border-bottom: 2px solid transparent;
    padding: 8px 12px; border-radius: 12px 12px 0 0; background: rgba(255,255,255,0.5);
  }}
  .stTabs [aria-selected="true"] {{
    border-color: rgba(5,82,88,0.28); border-bottom: 2px solid var(--primary); background: rgba(5,82,88,0.06);
  }}
</style>
'''
st.markdown(THEME_CSS, unsafe_allow_html=True)

# ====================
# CONSTANTS & SECRETS
# ====================
TOP_TIER_OUTLETS = {
    "The New York Times", "The Washington Post", "Reuters", "Bloomberg", "BBC News",
    "CNN", "The Wall Street Journal", "Financial Times", "The Guardian", "Politico",
    "NPR", "Associated Press", "Los Angeles Times", "TIME", "Forbes",
    "Fortune", "Vox", "Axios", "The Atlantic", "NBC News",
}
TOP_TIER_WEIGHT = 2.0
DEFAULT_WEIGHT = 1.0

# Secrets
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

# ====================
# HELPERS & CACHING
# ====================
def extract_domain(url: str):
    m = re.match(r"https?://([^/]+)/?", url or "")
    return m.group(1) if m else None

@st.cache_data(show_spinner=False, ttl=300)
def cached_get(url, params, headers=None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else r.text)
    except Exception as e:
        return -1, {"error": str(e)}

# NewsAPI
def get_newsapi_articles(topic: str, max_results: int, sort_by: str, d_from: str=None, d_to: str=None):
    if not NEWS_API_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {"q": topic, "apiKey": NEWS_API_KEY, "language": "en", "pageSize": max_results, "sortBy": sort_by}
    if d_from: params["from"] = d_from
    if d_to:   params["to"] = d_to
    code, data = cached_get(url, params)
    if code != 200: return []
    items = (data or {}).get("articles", []) or []
    out = []
    for it in items:
        title = (it.get("title") or "").strip()
        url_ = it.get("url") or ""
        if not title or not url_: continue
        out.append({
            "title": title,
            "url": url_,
            "source": (it.get("source") or {}).get("name") or "",
            "author": (it.get("author") or "").strip(),
            "publishedAt": it.get("publishedAt") or "",
        })
    return out

# Perigon - articles
def get_perigon_articles(topic: str, max_results: int, sort_by: str, d_from: str=None, d_to: str=None):
    if not PERIGON_API_KEY:
        return []
    url = "https://api.goperigon.com/v1/all"
    perigon_sort = "relevance" if sort_by == "relevancy" else "date"
    params = {"q": topic, "apiKey": PERIGON_API_KEY, "size": max_results, "sortBy": perigon_sort}
    if d_from: params["from"] = d_from
    if d_to:   params["to"] = d_to
    code, data = cached_get(url, params)
    if code != 200: return []
    items = (data or {}).get("articles") or (data or {}).get("data") or []
    out = []
    for it in items:
        title = (it.get("title") or it.get("headline") or "").strip()
        url_ = it.get("url") or it.get("link") or ""
        if not title or not url_: continue
        # source
        src = it.get("source")
        if isinstance(src, dict):
            source_name = (src.get("name") or src.get("domain") or "").strip()
        elif isinstance(src, str):
            source_name = src.strip()
        else:
            source_name = ""
        # author
        author = ""
        if isinstance(it.get("author"), str): author = it["author"].strip()
        elif isinstance(it.get("authors"), list) and it["authors"]:
            author = ", ".join([a for a in it["authors"] if isinstance(a, str)])[:200]
        out.append({
            "title": title,
            "url": url_,
            "source": source_name,
            "author": author,
            "publishedAt": it.get("publishedAt") or it.get("pubDate") or it.get("date") or "",
        })
    return out

# Perigon - journalists (enrichment)
@st.cache_data(show_spinner=False, ttl=3600)
def perigon_find_journalist(author_name: str, topic_query: str = ""):
    if not PERIGON_API_KEY or not author_name: return {}
    url = "https://api.goperigon.com/v1/journalists"
    params = {"apiKey": PERIGON_API_KEY, "q": author_name, "size": 1}
    if topic_query: params["topic"] = topic_query
    code, payload = cached_get(url, params)
    if code != 200 or not isinstance(payload, dict): return {}
    items = payload.get("journalists") or payload.get("data") or payload.get("results") or []
    if not items: return {}
    j = items[0]
    prof = {
        "name": j.get("name") or author_name,
        "title": j.get("title") or j.get("role") or "",
        "bio": j.get("bio") or "",
        "twitter": j.get("twitter") or j.get("twitter_handle") or "",
        "linkedin": j.get("linkedin") or j.get("linkedin_url") or "",
        "location": j.get("location") or "",
        "topics": j.get("topics") or j.get("top_topics") or [],
        "sources": j.get("top_sources") or j.get("sources") or [],
    }
    if isinstance(prof["topics"], list): prof["topics"] = [str(t) for t in prof["topics"]]
    if isinstance(prof["sources"], list): prof["sources"] = [str(s) for s in prof["sources"]]
    return prof

# Combine & dedupe
def search_articles(topic: str, max_results: int, sort_by: str, d_from: str=None, d_to: str=None):
    a = get_newsapi_articles(topic, max_results, sort_by, d_from, d_to)
    b = get_perigon_articles(topic, max_results, sort_by, d_from, d_to)
    combined, seen = [], set()
    for lst in (a, b):
        for it in lst:
            url = (it.get("url") or "").strip().lower()
            if not url or url in seen: continue
            seen.add(url)
            combined.append(it)
    return combined

def hunter_email(domain: str):
    if not HUNTER_API_KEY: return None
    url = "https://api.hunter.io/v2/domain-search"
    code, data = cached_get(url, {"domain": domain, "api_key": HUNTER_API_KEY, "limit": 1})
    if code != 200 or not isinstance(data, dict): return None
    emails = data.get("data", {}).get("emails", [])
    return emails[0].get("value") if emails else None

def outlet_weight_for(outlet_name: str):
    if not outlet_name: return DEFAULT_WEIGHT
    cleaned = outlet_name.strip()
    if cleaned in TOP_TIER_OUTLETS: return TOP_TIER_WEIGHT
    for t in TOP_TIER_OUTLETS:
        if cleaned.lower() == t.lower(): return TOP_TIER_WEIGHT
    return DEFAULT_WEIGHT

def recency_weight(published_iso: str, half_life_days: float = 30.0):
    if not published_iso: return 1.0
    try:
        dt = dateparser.parse(published_iso)
        if not dt: return 1.0
        days_old = max(0.0, (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() / 86400.0)
        return pow(0.5, days_old / half_life_days)
    except Exception:
        return 1.0

# ====================
# AUTH
# ====================
def login_block(sidebar: bool = True) -> bool:
    """Streamlit login form with proper state handling."""
    # If no creds configured, disable auth
    if not APP_USERNAME or not APP_PASSWORD:
        return True
    container = st.sidebar if sidebar else st
    if st.session_state.auth:
        with container:
            st.markdown(f"✅ **Signed in as {st.session_state.user or APP_USERNAME}**")
        return True
    with container:
        u = st.text_input("Username", key="login_user")
        p = st.text_input("Password", type="password", key="login_pass")
        clicked = st.button("Sign in", type="primary", key="login_btn")
        if clicked:
            if u == APP_USERNAME and p == APP_PASSWORD:
                st.session_state.auth = True
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Invalid username or password")
    return False

# ====================
# HEADER
# ====================
def render_header():
    st.markdown('''
    <div class="app-header">
      <h1>📰 Reporter Finder</h1>
      <div class="app-sub">Search by topic to find relevant articles and rank reporters, with optional enrichment.</div>
    </div>
    ''', unsafe_allow_html=True)

# ====================
# MAIN
# ====================
render_header()

with st.sidebar:
    st.subheader("Authentication")
if not login_block(sidebar=True):
    st.stop()

with st.sidebar:
    st.subheader("Search Settings")
    topic = st.text_input("Topic", placeholder="e.g., AI in healthcare")
    max_results = st.slider("Articles to fetch (per source)", 20, 200, 100)
    # 'publishedAt' removed
    sort_by = st.selectbox("Sort articles by", ["relevancy", "popularity"], index=0)
    today = datetime.utcnow().date()
    default_from = today - timedelta(days=30)
    d_range = st.date_input("Date range", (default_from, today))
    if isinstance(d_range, tuple) and len(d_range) == 2:
        d_from_val, d_to_val = d_range
    else:
        d_from_val, d_to_val = default_from, today
    def iso_date(d: date):
        if not d: return None
        return datetime(d.year, d.month, d.day).isoformat()
    d_from_iso = iso_date(d_from_val)
    d_to_iso = iso_date(d_to_val + timedelta(days=1))  # inclusive
    enrich_emails = st.checkbox("Enrich with emails (Hunter.io)", value=bool(HUNTER_API_KEY))
    enrich_journalists = st.checkbox("Enrich reporter profiles (Perigon)", value=bool(PERIGON_API_KEY))
    scoring_method = st.selectbox("Scoring method",
                                  ["Frequency only", "Prominence-weighted", "Recency-weighted", "Hybrid (Freq × Prominence × Recency)"],
                                  index=1)
    run = st.button("Search", type="primary")

if run:
    if not topic.strip():
        st.error("Please enter a topic."); st.stop()
    with st.spinner("Fetching from NewsAPI + Perigon…"):
        articles = search_articles(topic, max_results, sort_by, d_from_iso, d_to_iso)
    tab_articles, tab_reporters = st.tabs(["📰 Articles", "🧑‍💼 Reporters"])

    # Articles tab
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
            st.dataframe(pd.DataFrame(art_rows), use_container_width=True, hide_index=True)
            csv_articles = pd.DataFrame([
                {"Title": a["title"], "URL": a["url"], "Outlet": a["source"], "Author": a["author"], "PublishedAt": a["publishedAt"]}
                for a in articles
            ]).to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download articles CSV", data=csv_articles, file_name="articles.csv", mime="text/csv")

    # Reporters tab
    with tab_reporters:
        reporters = {}
        for a in articles:
            author = (a.get("author") or "").strip()
            title = (a.get("title") or "").strip()
            url = a.get("url")
            outlet = (a.get("source") or "").strip()
            published = a.get("publishedAt")
            if not author or not url: continue
            reporters.setdefault(author, {"author": author, "outlets": set(), "articles": [], "profile": {}})
            reporters[author]["outlets"].add(outlet)
            reporters[author]["articles"].append({"title": title, "url": url, "outlet": outlet, "published": published})

        def outlet_weight_for_local(name):  # shadow for quick use
            return outlet_weight_for(name)

        def score_reporter(articles_list, outlets_set):
            prominence = max([outlet_weight_for_local(o) for o in outlets_set if o] or [DEFAULT_WEIGHT])
            if scoring_method == "Frequency only":
                return float(len(articles_list))
            elif scoring_method == "Prominence-weighted":
                return float(len(articles_list)) * prominence
            elif scoring_method == "Recency-weighted":
                return sum(recency_weight(a.get("published")) for a in articles_list)
            else:
                rec = sum(recency_weight(a.get("published")) for a in articles_list)
                rec_norm = rec / max(1.0, len(articles_list))
                return float(len(articles_list)) * prominence * rec_norm

        rows = []
        for author, info in reporters.items():
            arts = info["articles"]
            outs = info["outlets"]
            score = score_reporter(arts, outs)
            try:
                arts_sorted = sorted(arts, key=lambda x: dateparser.parse(x.get("published") or ""), reverse=True)
            except Exception:
                arts_sorted = arts
            top_articles = arts_sorted[:5]
            outlets_str = ", ".join(sorted({o for o in outs if o}))
            email = ""
            if enrich_emails and top_articles:
                domain = extract_domain(top_articles[0].get("url") or "") or ""
                if domain: email = hunter_email(domain) or ""
            profile = perigon_find_journalist(author, topic_query=topic) if enrich_journalists else {}
            rows.append({
                "Reporter": author, "Outlets": outlets_str, "ArticlesMatched": len(arts),
                "Score": score, "TopArticles": top_articles, "Email": email, "Profile": profile
            })

        if not rows:
            st.warning("No reporters found.")
        else:
            df = pd.DataFrame(rows).sort_values(by=["Score", "ArticlesMatched"], ascending=False)
            st.success(f"Found {len(df)} reporters (merged from NewsAPI + Perigon).")
            st.markdown("---")
            for _, r in df.reset_index(drop=True).iterrows():
                sc = float(r['Score'])
                if sc > 10: sc_cls = "badge-score-top"
                elif sc > 5: sc_cls = "badge-score-high"
                elif sc > 2: sc_cls = "badge-score-mid"
                else: sc_cls = "badge-score-low"

                st.markdown('<div class="card">', unsafe_allow_html=True)
                cols = st.columns([3, 3, 1, 1, 1])
                header = r['Reporter']
                prof = r.get("Profile") or {}
                title_suffix = f" — {prof['title']}" if prof.get("title") else ""
                cols[0].markdown(f"**{header}**{title_suffix}")
                cols[1].write(r['Outlets'])
                cols[2].write(int(r['ArticlesMatched']))
                cols[3].markdown(f'<span class="badge {sc_cls}">Score: {sc:.2f}</span>', unsafe_allow_html=True)
                cols[4].write(r['Email'] or "")

                with st.expander("Recent articles (click to open)"):
                    for art in r['TopArticles']:
                        title = art.get('title') or art.get('url')
                        url = art.get('url')
                        pub = art.get('published') or ''
                        st.markdown(f"- [{title}]({url}) <small>({pub})</small>", unsafe_allow_html=True)

                if prof:
                    with st.expander("Journalist profile (Perigon)"):
                        if prof.get("bio"): st.markdown(f"**Bio:** {prof['bio']}")
                        meta_cols = st.columns(3)
                        meta_cols[0].markdown(f"**Location:** {prof.get('location','')}")
                        meta_cols[1].markdown(f"**Twitter:** {prof.get('twitter','')}")
                        meta_cols[2].markdown(f"**LinkedIn:** {prof.get('linkedin','')}")
                        topics = prof.get("topics") or []
                        sources = prof.get("sources") or []
                        if topics: st.markdown("**Top topics:** " + ", ".join(topics[:10]))
                        if sources: st.markdown("**Top sources:** " + ", ".join(sources[:10]))
                st.markdown('</div>', unsafe_allow_html=True)

            csv_rows = [{
                "Reporter": r["Reporter"], "Outlets": r["Outlets"], "ArticlesMatched": r["ArticlesMatched"],
                "Score": r["Score"], "Email": r["Email"],
                "ProfileTitle": (r.get("Profile") or {}).get("title",""),
                "ProfileTopics": ", ".join((r.get("Profile") or {}).get("topics", [])[:10]),
            } for r in rows]
            csv_df = pd.DataFrame(csv_rows).sort_values(by=["Score", "ArticlesMatched"], ascending=False)
            csv = csv_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download reporters CSV", data=csv, file_name="reporters_merged.csv", mime="text/csv")

st.caption("Use responsibly. Verify contacts before outreach and follow each API’s terms.")
