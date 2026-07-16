"""Setup page: API keys + one-time setup status.

Moved out of the sidebar into its own page (listed under Analytics in the nav).
"""

import os

import streamlit as st

from gmap_planner.appconfig import (
    cached_update_check,
    get_secret,
    load_app_config,
    run_update,
    save_app_config,
)
from gmap_planner.config import (
    DRIVE_CREDENTIALS_FILE,
    DRIVE_TOKEN_FILE,
    PW_PROFILE_DIR,
)
from gmap_planner.updater import current_version

st.set_page_config(page_title="Setup", page_icon="⚙️", layout="centered")
st.title("⚙️ Setup")


def _dir_has_files(path: str) -> bool:
    try:
        return os.path.isdir(path) and any(os.scandir(path))
    except OSError:
        return False


def render_setup_status() -> None:
    """One-glance green/red list of the one-time setup items (local use)."""
    rows = [
        (bool(get_secret("GOOGLE_API_KEY")), "Gemini API key",
         "Set it under Settings (API keys) above"),
        (bool(get_secret("GEO_API_KEY")), "Geocoding API key",
         "Set it under Settings (API keys) above"),
        (_dir_has_files(PW_PROFILE_DIR), "Signed in to Google (My Maps)",
         "Run login.bat once (only needed to publish maps)"),
        (os.path.exists(DRIVE_CREDENTIALS_FILE), "Drive credentials.json",
         "Only needed to share maps — upload it under 'Publish to My Maps'"),
        (os.path.exists(DRIVE_TOKEN_FILE), "Drive access authorized",
         "Granted automatically the first time you share a map"),
    ]
    for ok, label, hint in rows:
        if ok:
            st.markdown(f"✅ {label}")
        else:
            st.markdown(f"⚪ {label}  \n<small>{hint}</small>", unsafe_allow_html=True)


def render_settings() -> None:
    """Let the admin enter/save keys + settings without editing files (for the exe)."""
    cfg = load_app_config()
    st.caption("Saved on this computer. Needed once.")
    gk = st.text_input("Gemini API key (GOOGLE_API_KEY)", value=cfg.get("GOOGLE_API_KEY", ""),
                       type="password", key="cfg_gemini")
    gek = st.text_input("Geocoding API key (GEO_API_KEY)", value=cfg.get("GEO_API_KEY", ""),
                        type="password", key="cfg_geo")

    st.markdown("**Usage gauges (optional)**")
    st.caption("Fill these to show the live Geocoding-usage gauge. Needs the Cloud "
               "Monitoring API enabled and a service account with `roles/monitoring.viewer`.")
    proj = st.text_input("GCP project id (GCP_PROJECT_ID)", value=cfg.get("GCP_PROJECT_ID", ""),
                         key="cfg_proj")
    sa_json = st.text_area("Service-account JSON (GCP_SA_JSON)", value=cfg.get("GCP_SA_JSON", ""),
                           height=120, key="cfg_sa",
                           help="Paste the whole downloaded service-account .json here.")

    st.markdown("**Analytics (optional)**")
    st.caption("The Google Sheet the publish log is written to and read from. "
               "Share the Sheet with the `GCP_SA_JSON` service-account email and "
               "enable the Google Sheets API.")
    sheet_id = st.text_input("Analytics Sheet id or URL (ANALYTICS_SHEET_ID)",
                             value=cfg.get("ANALYTICS_SHEET_ID", ""), key="cfg_sheet")

    if st.button("Save settings", use_container_width=True):
        cfg["GOOGLE_API_KEY"] = gk.strip()
        cfg["GEO_API_KEY"] = gek.strip()
        cfg["GCP_PROJECT_ID"] = proj.strip()
        cfg["GCP_SA_JSON"] = sa_json.strip()
        cfg["ANALYTICS_SHEET_ID"] = sheet_id.strip()
        save_app_config(cfg)
        st.success("Saved. They'll be used on the next run.")


def render_updates() -> None:
    """Current version + a manual 'Check for updates' (installs from GitHub Releases)."""
    st.caption(f"Current version: **v{current_version()}**")
    if st.button("Check for updates"):
        cached_update_check.clear()  # force a fresh GitHub query, bypass the 1h cache
    info = cached_update_check()
    if info is None:
        st.caption("Couldn't check right now — offline, or GitHub is unreachable.")
    elif info.has_update:
        st.info(f"🔄 Update available: **v{info.latest}** (you have v{info.current}).")
        if info.notes:
            with st.expander("What's new"):
                st.markdown(info.notes)
        if st.button("Update now", type="primary", key="update_now_setup"):
            run_update(info)
    else:
        st.success("You're on the latest version.")


st.subheader("🔑 Settings (API keys)")
render_settings()

st.divider()

st.subheader("🔄 Updates")
render_updates()

st.divider()

st.subheader("⚙️ Setup status")
render_setup_status()
