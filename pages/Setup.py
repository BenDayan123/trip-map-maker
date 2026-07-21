"""Setup page: API keys + one-time setup status.

Moved out of the sidebar into its own page (listed under Analytics in the nav).
"""

import json
import os

import streamlit as st

from gmap_planner.appconfig import (
    apply_setup_bundle,
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


# Manual input widget key -> config key, so an uploaded file fills those fields.
_FIELD_KEYS = {
    "cfg_gemini": "GOOGLE_API_KEY",
    "cfg_geo": "GEO_API_KEY",
    "cfg_sa": "GCP_SA_JSON",
    "cfg_sheet": "ANALYTICS_SHEET_ID",
}


def render_one_file_setup() -> None:
    """Upload one JSON that fills every setting below + writes credentials.json."""
    st.caption(
        "Upload a single JSON to fill in every setting below — API keys, the "
        "service-account JSON, and the Drive `credentials.json` (written "
        "automatically). Any key not in the file keeps its current value."
    )
    up = st.file_uploader("Setup file (.json)", type=["json"], key="setup_bundle")

    # Result of the last apply (set just before the rerun that filled the fields).
    msg = st.session_state.pop("_setup_bundle_applied", None)
    if msg is not None:
        if msg:
            st.success("Loaded into the fields below: " + ", ".join(msg) + ".")
        else:
            st.warning("Nothing loaded — no recognized keys in the file.")

    if up is None:
        return
    # Apply each newly-uploaded file exactly once.
    fid = getattr(up, "file_id", None) or up.name
    if st.session_state.get("_setup_bundle_done") == fid:
        return
    try:
        bundle = json.loads(up.getvalue().decode("utf-8"))
        if not isinstance(bundle, dict):
            raise ValueError("the file must contain a JSON object")
    except Exception as e:
        st.error(f"Not a valid setup file: {e}")
        return

    applied = apply_setup_bundle(bundle)  # saves config.json + writes credentials.json
    st.session_state.pop("usage", None)  # force one usage refresh with the new keys
    st.session_state["_setup_bundle_done"] = fid
    # Push the saved values into the manual input widgets so they show them.
    cfg = load_app_config()
    for wkey, ckey in _FIELD_KEYS.items():
        if ckey in cfg:
            st.session_state[wkey] = cfg[ckey]
    st.session_state["_setup_bundle_applied"] = applied
    st.rerun()


def _project_id_of(sa_json: str) -> str | None:
    """The project id inside a pasted service-account JSON, if it parses."""
    try:
        return json.loads(sa_json).get("project_id") or None
    except Exception:
        return None


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
    """Let the admin enter/save keys + settings without editing files (for the exe).

    Field values live in session_state (keyed cfg_*), seeded from the saved config;
    an uploaded setup file sets those same keys, so the fields show its values.
    """
    cfg = load_app_config()
    for wkey, ckey in _FIELD_KEYS.items():
        st.session_state.setdefault(wkey, cfg.get(ckey, ""))

    st.caption("Saved on this computer. Needed once.")
    gk = st.text_input("Gemini API key (GOOGLE_API_KEY)", type="password", key="cfg_gemini")
    gek = st.text_input("Geocoding API key (GEO_API_KEY)", type="password", key="cfg_geo")

    st.markdown("**Usage gauges (optional)**")
    st.caption("Paste the service-account JSON to show the live Geocoding-usage gauge — "
               "the project is read from it. Needs the Cloud Monitoring API enabled and "
               "a service account with `roles/monitoring.viewer`.")
    sa_json = st.text_area("Service-account JSON (GCP_SA_JSON)", height=120, key="cfg_sa",
                           help="Paste the whole downloaded service-account .json here.")
    proj = _project_id_of(sa_json)
    if proj:
        st.caption(f"Project: `{proj}` (read from the service-account JSON).")
    elif sa_json.strip():
        st.warning("Couldn't read a `project_id` from that JSON — paste the whole file.")

    st.markdown("**Analytics (optional)**")
    st.caption("The Google Sheet the publish log is written to and read from. "
               "Share the Sheet with the `GCP_SA_JSON` service-account email and "
               "enable the Google Sheets API.")
    sheet_id = st.text_input("Analytics Sheet id or URL (ANALYTICS_SHEET_ID)", key="cfg_sheet")

    if st.button("Save settings", use_container_width=True):
        cfg["GOOGLE_API_KEY"] = gk.strip()
        cfg["GEO_API_KEY"] = gek.strip()
        cfg.pop("GCP_PROJECT_ID", None)  # derived from GCP_SA_JSON now
        cfg["GCP_SA_JSON"] = sa_json.strip()
        cfg["ANALYTICS_SHEET_ID"] = sheet_id.strip()
        save_app_config(cfg)
        st.session_state.pop("usage", None)  # force one usage refresh with the new keys
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
        if not info.has_asset:
            st.warning(
                "This release has no installer attached for your system yet — "
                "nothing to download. It'll be installable once the build finishes."
            )
        elif st.button("Update now", type="primary", key="update_now_setup"):
            run_update(info)
    else:
        st.success("You're on the latest version.")


st.subheader("📦 One-file setup")
render_one_file_setup()

st.divider()

st.subheader("🔑 Settings (API keys)")
st.caption("Or set individual values by hand.")
render_settings()

st.divider()

st.subheader("🔄 Updates")
render_updates()

st.divider()

st.subheader("⚙️ Setup status")
render_setup_status()
