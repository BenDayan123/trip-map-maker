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


def get_secret(name: str) -> str | None:
    """Setting resolved from Streamlit secrets, then env, then the saved config.json.

    The config.json fallback is what makes the packaged exe usable: there's no
    secrets.toml to edit, so the admin enters keys in the Setup page instead.
    """
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass  # no secrets.toml present (e.g. packaged exe) — fall back below
    return os.environ.get(name) or load_app_config().get(name)


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
