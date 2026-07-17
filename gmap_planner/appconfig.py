"""Shared app-config helpers for the Streamlit UI.

Kept in its own module so both the main "Make Map" page and the Setup page can
import them without executing the app script at import time.
"""

import json
import os
import sys

import streamlit as st

from gmap_planner.paths import data_path


def _app_config_path() -> str:
    return data_path("config.json")


def load_app_config() -> dict:
    """Settings the admin saved via the Setup page (data_dir/config.json)."""
    try:
        with open(_app_config_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_app_config(cfg: dict) -> None:
    with open(_app_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# Config keys stored in config.json (the sidebar/Setup fields).
SETUP_KEYS = [
    "GOOGLE_API_KEY",
    "GEO_API_KEY",
    "GCP_PROJECT_ID",
    "GCP_SA_JSON",
    "ANALYTICS_SHEET_ID",
]
# Bundle keys that map to the Drive OAuth client file (credentials.json), not config.json.
_CRED_ALIASES = ("credentials", "credentials.json", "DRIVE_CREDENTIALS")


def _as_text(v) -> str | None:
    """A bundle value as text: JSON objects are re-serialized, scalars stringified."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def apply_setup_bundle(bundle: dict) -> list[str]:
    """Merge a one-file setup bundle into config.json + credentials.json.

    Only keys present (and non-empty) in the bundle are written; anything missing
    keeps its current value. `GCP_SA_JSON` and `credentials` accept either a JSON
    object or a JSON string. Returns the list of fields actually applied.
    """
    from gmap_planner.config import DRIVE_CREDENTIALS_FILE

    applied: list[str] = []
    cfg = load_app_config()
    for key in SETUP_KEYS:
        if key not in bundle:
            continue
        val = _as_text(bundle[key])
        if val is None or not val.strip():
            continue  # present but empty → keep current value
        cfg[key] = val.strip()
        applied.append(key)
    save_app_config(cfg)

    # Drive OAuth client credentials.json lives as a file, not a config key.
    cred = next((bundle[k] for k in _CRED_ALIASES if bundle.get(k)), None)
    if cred is not None:
        text = _as_text(cred)
        try:
            json.loads(text)  # validate it's real JSON before writing
            with open(DRIVE_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                f.write(text)
            applied.append("credentials.json")
        except Exception:
            pass  # not valid JSON — skip rather than corrupt the file

    return applied


def get_secret(name: str) -> str | None:
    """Setting resolved from the admin's saved config.json first, then Streamlit
    secrets, then env.

    config.json (the Setup page) is the admin's source of truth in the local /
    packaged app, so it must WIN over any stale ``.streamlit/secrets.toml`` — a
    value edited in Setup takes effect immediately instead of being shadowed by
    an old secrets entry. Secrets/env remain fallbacks for hosted runs where
    config.json is absent.
    """
    val = load_app_config().get(name)
    if val:
        return val
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass  # no secrets.toml present (e.g. packaged exe)
    return os.environ.get(name)


# --- In-app updater (GitHub Releases) -------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def cached_update_check():
    """Latest-release check, cached for an hour so app reruns/launches don't
    hammer the GitHub API. Returns an UpdateInfo or None (offline/failure)."""
    from gmap_planner.updater import check_for_update

    return check_for_update()


def run_update(info) -> None:
    """Download the release installer and launch it (shared by the banner + Setup)."""
    if not getattr(sys, "frozen", False):
        st.warning(
            "You're running from source, not the packaged app — update by "
            "pulling the latest code and rebuilding, not through here."
        )
        return
    if not getattr(info, "has_asset", False):
        st.error(
            f"v{info.latest} is published but has no installer for your system "
            "yet — the release is missing its download. Try again once the build "
            "has attached it."
        )
        return
    from gmap_planner.updater import apply_update, download_asset

    try:
        bar = st.progress(0.0, text=f"Downloading {info.asset_name}…")
        path = download_asset(
            info.asset_url, info.asset_name, progress=lambda f: bar.progress(f)
        )
        bar.progress(1.0, text="Starting the installer…")
        apply_update(path)
        if sys.platform == "darwin":
            st.success(
                "Downloaded. The disk image opened — drag **Trip Map Maker** into "
                "Applications, replacing the old one, then reopen it."
            )
        else:
            st.success(
                "Updating… the app will close and reopen on the new version."
            )
    except Exception as e:
        st.error(f"Update failed: {e}")
