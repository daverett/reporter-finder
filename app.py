import os
from pathlib import Path
import streamlit as st
import pandas as pd
from packaging import version

# ---- Safety check for rich/streamlit combo (see section 1)
try:
    import rich
    if version.parse(rich.__version__) >= version.parse("14.0.0"):
        st.warning(
            f"Detected rich {rich.__version__}. Streamlit 1.37.0 requires rich<14. "
            "Fix with: pip install 'rich<14'"
        )
except Exception:
    pass

# ---- Page & Theme
st.set_page_config(
    page_title="Reporter Finder",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- Sidebar
with st.sidebar:
    st.markdown("### Reporter Finder")
    st.caption("Narrow by beat, outlet, location, and recency.")
    st.divider()

    default_beats = ["tech", "business", "policy", "science", "sports", "culture"]
    beats = st.multiselect("Beats (global filter)", options=default_beats, default=["tech", "business"])
    locations = st.text_input("Locations (comma-separated)", placeholder="e.g., New York, SF, London")
    recency_days = st.slider("Recency (days)", 7, 365, 90, help="Filter by how recent articles/activities should be.")
    st.divider()

    st.caption("Data sources")
    source_toggle = st.toggle("Use external sources", value=True, help="Turn off to use only local cache.")

# ---- Session State
if "reporter_query" not in st.session_state:
    st.session_state.reporter_query = ""
if "article_query" not in st.session_state:
    st.session_state.article_query = ""

st.title("Reporter Finder")

tab_reporter, tab_articles = st.tabs(["Reporter", "Articles"])

# Reporter Tab
with tab_reporter:
    st.subheader("Find Reporters")

    colL, colR = st.columns([2, 1], gap="large")
    with colL:
        q = st.text_input(
            "Search by name, outlet, keyword…",
            value=st.session_state.reporter_query,
            placeholder="e.g., Casey Newton, Semafor, 'AI policy', 'startups funding'",
            key="reporter_query_input",
        )
        adv = st.expander("Advanced filters", expanded=False)
        with adv:
            outlet = st.text_input("Outlet", placeholder="e.g., The Verge")
            title_kw = st.text_input("Title keywords", placeholder="e.g., editor, correspondent")
            exclude_kw = st.text_input("Exclude keywords", placeholder="e.g., sports, opinion")

    with colR:
        min_articles = st.number_input("Min. recent articles", min_value=0, max_value=200, value=3, step=1)
        has_email = st.checkbox("Must have email", value=False)
        on_twitter = st.checkbox("Active on X/Twitter", value=False)

    run = st.button("Search reporters", type="primary")
    st.caption("Tip: combine name + outlet + beat for best precision.")

    if run:
        sample = [
            {"name": "Casey Newton", "outlet": "Platformer", "beats": "tech, policy", "location": "SF", "email": "—", "recent_articles": 12},
            {"name": "Zoe Schiffer", "outlet": "Platformer", "beats": "tech, labor", "location": "NY", "email": "—", "recent_articles": 9},
            {"name": "Jane Doe", "outlet": "The Verge", "beats": "AI, startups", "location": "NY", "email": "jane@theverge.com", "recent_articles": 7},
        ]
        df = pd.DataFrame(sample)
        st.write(f"Found **{len(df)}** reporters")
        st.dataframe(df, use_container_width=True)

# Articles Tab
with tab_articles:
    st.subheader("Search Articles")

    col1, col2 = st.columns([2, 1], gap="large")
    with col1:
        q2 = st.text_input(
            "Keywords, title, domain…",
            value=st.session_state.article_query,
            placeholder='e.g., "openAI board", site:theverge.com, author:"John Doe"',
            key="article_query_input",
        )
        filters = st.expander("Filters", expanded=False)
        with filters:
            domains = st.text_input("Limit to domains (comma-separated)", placeholder="e.g., theverge.com, semafor.com")
            author = st.text_input("Author contains", placeholder="e.g., Newton")
            exclude = st.text_input("Exclude words", placeholder="e.g., rumor, opinion")

    with col2:
        min_words = st.number_input("Min. word count", min_value=0, max_value=5000, value=400, step=50)
        only_verified = st.checkbox("Only verified sources", value=False)
        link_export = st.checkbox("Include shareable links", value=True)

    run2 = st.button("Search articles", type="secondary")

    if run2:
        rows = [
            {"title": "AI safety bill advances", "author": "Jane Doe", "outlet": "The Verge", "url": "https://example.com/a", "published": "2025-09-14"},
            {"title": "Startups pivot to edge AI", "author": "John Roe", "outlet": "Semafor", "url": "https://example.com/b", "published": "2025-09-11"},
        ]
        df_articles = pd.DataFrame(rows)
        st.write(f"Found **{len(df_articles)}** articles")
        st.dataframe(df_articles, use_container_width=True)
        if link_export and not df_articles.empty:
            csv = df_articles.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, "articles.csv", "text/csv")

st.caption("Hint: toggle data sources in the sidebar, refine by beats & recency, then switch tabs.")
