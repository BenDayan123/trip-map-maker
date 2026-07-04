"""Shared app-config helpers for the Streamlit UI.

Kept in its own module so both the main "Make Map" page and the Setup page can
import them without executing the app script at import time.
"""

import json
import os

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
