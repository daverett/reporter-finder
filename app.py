import os
import re
from datetime import datetime, timedelta, date
import streamlit as st
import pandas as pd
import requests
from dateutil import parser as dateparser

# ====================
# CONFIG
# ====================
st.set_page_config(page_title="Reporter Finder", page_icon="📰", layout="wide")

# Initialize session state
if "auth" not in st.session_state:
    st.session_state.auth = False
if "user" not in st.session_state:
    st.session_state.user = None

# ====================
# COLORS
# ====================
PRIMARY = "#055258"
ACCENT = "#35ce8d"
SAGE = "#6ba292"
SOFT_WHITE = "#e5e0e0"
DARK = "#303030"

st.markdown(f"""<style>
    .stApp {{background-color:{SOFT_WHITE}; color:{DARK};}}
    h1, h2, h3, h4, h5 {{color:{PRIMARY};}}
    .app-header {{
        background: linear-gradient(to right, rgba(5,82,88,0.12), rgba(53,206,141,0.12));
        border-radius:14px; padding:14px 18px; margin-bottom:12px;
        border:1px solid rgba(5,82,88,0.15);
    }}
    .app-header h1 {{margin:0; font-size:1.6rem;}}
    .app-sub {{color:{DARK}; opacity:0.85; font-size:0.95rem;}}
</style>""", unsafe_allow_html=True)

# ====================
# AUTH HELPERS
# ====================
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme")

def login_block(sidebar: bool = True) -> bool:
    """Streamlit login form with proper state handling."""
    if not APP_USERNAME or not APP_PASSWORD:
        return True

    container = st.sidebar if sidebar else st

    # Already authed: show signed-in state
    if st.session_state.auth:
        with container:
            st.markdown(f"✅ **Signed in as {st.session_state.user or APP_USERNAME}**")
        return True

    # Render login inputs
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
    st.markdown(f"""<div class='app-header'>
        <h1>📰 Reporter Finder</h1>
        <div class='app-sub'>Search and rank reporters by topic, outlet, and coverage.</div>
    </div>""", unsafe_allow_html=True)

# ====================
# MAIN APP
# ====================
render_header()

with st.sidebar:
    st.subheader("Authentication")

auth_ok = login_block(sidebar=True)
if not auth_ok:
    st.stop()

st.success("Login successful. Ready for next steps of integration.")
st.write("This is the patched version with the fixed login system.")
