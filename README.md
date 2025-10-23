# Reporter Finder — Dependency Fix

This patch resolves the dependency conflict between **Streamlit 1.37.0** and **rich 14.x**.

## What's Changed
- Pinned `rich` to version **13.7.1** (compatible with Streamlit 1.37)
- Added `runtime.txt` to enforce **Python 3.11** in Streamlit Cloud

## Deploy Instructions
1. Replace your existing `requirements.txt` with this version.
2. Add `runtime.txt` to your repository root.
3. Redeploy your app on Streamlit Cloud.

This ensures dependency stability and prevents `pip resolver` warnings.
