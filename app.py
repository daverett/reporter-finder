import os
from pathlib import Path
import streamlit as st
import pandas as pd
from packaging import version

# ---- Safety check for rich/streamlit combo
try:
    import rich
    if version.parse(rich.__version__) >= version.parse("14.0.0"):
        st.warning(
            f"Detected rich {rich.__version__}. Streamlit 1.37.0 requires rich<14. "
            "Fix with: pip install 'rich<14'"
        )
except Exception:
    pass

# ---- Page
st.set_page_config(
    page_title="Reporter Finder",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Helpers
def _parse_keywords(s: str) -> list[str]:
    if not s:
        return []
    raw = [p.strip() for chunk in s.split(",") for p in chunk.split(" ") if p.strip()]
    seen, out = set(), []
    for w in raw:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            out.append(w)
    return out

def _parse_csv(s: str) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]

# ---- Sidebar (Autocomplete chips with graceful fallback to freeform text)
with st.sidebar:
    st.markdown("### Reporter Finder")
    st.caption("Narrow by beat, outlet, location, and recency.")
    st.divider()

    beats = []
    used_fallback = False
    try:
        from streamlit_tags import st_tags  # type: ignore
        suggested_beats = [
            "ai", "startups", "labor", "antitrust", "policy", "cloud", "cybersecurity",
            "privacy", "elections", "regulation", "saas", "venture", "hardware",
            "mobility", "health", "fintech", "gaming", "media", "sports"
        ]
        beats = st_tags(
            label="Beats (keywords)",
            text="Type a beat and press Enter",
            value=[],
            suggestions=suggested_beats,
            maxtags=12,
            key="beats_tags",
        )
    except Exception:
        used_fallback = True
        beats_text = st.text_input(
            "Beats (keywords)",
            value="",
            placeholder="e.g., ai, startups, labor, antitrust"
        )
        beats = _parse_keywords(beats_text)

    locations = st.text_input("Locations (comma-separated)", placeholder="e.g., New York, SF, London")
    recency_days = st.slider("Recency (days)", 7, 365, 90, help="How recent should items be.")
    strict = st.toggle("Strict filters", value=False, help="Off = broader results; filters act as ranking boosts.")
    st.divider()

    st.caption("Data sources")
    source_toggle = st.toggle("Use external sources", value=True, help="Turn off to use only local cache.")

    if used_fallback:
        st.caption("Tip: Install optional dependency `streamlit-tags` for autocomplete chips.")

# ---- Session State
if "reporter_query" not in st.session_state:
    st.session_state.reporter_query = ""
if "article_query" not in st.session_state:
    st.session_state.article_query = ""

st.title("Reporter Finder")
tab_reporter, tab_articles = st.tabs(["Reporter", "Articles"])

# ---------------------- Reporter Tab
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
        # --- Replace this with your actual implementation
        # Example stub showing how 'beats' integrates as freeform keywords
        sample = [
            {"name": "Casey Newton", "outlet": "Platformer", "beats": "tech, policy", "location": "SF", "email": "—", "recent_articles": 12},
            {"name": "Zoe Schiffer", "outlet": "Platformer", "beats": "tech, labor", "location": "NY", "email": "—", "recent_articles": 9},
            {"name": "Jane Doe", "outlet": "The Verge", "beats": "AI, startups", "location": "NY", "email": "jane@theverge.com", "recent_articles": 7},
        ]
        df = pd.DataFrame(sample)

        # Simulate stricter filtering vs ranking when 'strict' is on/off
        if beats:
            mask = df["beats"].str.contains("|".join([b for b in beats]), case=False, na=False)
            if strict:
                df = df[mask].copy()
            else:
                # rank boost: move matches to top
                df["rank_boost"] = mask.astype(int)
                df = df.sort_values(["rank_boost", "recent_articles"], ascending=[False, False]).drop(columns=["rank_boost"])

        if df.empty and not strict and recency_days < 365:
            # Recency backoff demo (in your real search, widen date window)
            st.info("Expanded recency window to widen results.")

        st.write(f"Found **{len(df)}** reporters")
        st.dataframe(df, use_container_width=True)

# ---------------------- Articles Tab
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

        # Example: apply beats as soft filter to article titles if provided
        if beats:
            mask = df_articles["title"].str.contains("|".join([b for b in beats]), case=False, na=False)
            if strict:
                df_articles = df_articles[mask].copy()
            else:
                df_articles["rank_boost"] = mask.astype(int)
                df_articles = df_articles.sort_values(["rank_boost", "published"], ascending=[False, False]).drop(columns=["rank_boost"])

        st.write(f"Found **{len(df_articles)}** articles")
        st.dataframe(df_articles, use_container_width=True)
        if link_export and not df_articles.empty:
            csv = df_articles.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, "articles.csv", "text/csv")

st.caption("Hint: Beats are now freeform keywords with autocomplete (if 'streamlit-tags' is installed).")
