"""Where the app keeps its per-user files (login profile, tokens, credentials, keys).

Locally this is just the project directory (unchanged behavior). Inside a packaged
desktop exe the working directory is a temporary unpack folder that's wiped on exit,
so persistent files must live in a stable per-user location (``%APPDATA%\\TripMapMaker``
on Windows). Override with the ``TRIP_MAP_DATA_DIR`` env var.
"""

import os
import sys

APP_NAME = "TripMapMaker"


def data_dir() -> str:
    """Return the writable directory for persistent app files (created if needed)."""
    override = os.environ.get("TRIP_MAP_DATA_DIR")
    if override:
        base = override
    elif getattr(sys, "frozen", False):
        # Packaged app: use the OS's per-user data folder, not the temp unpack dir.
        if sys.platform == "darwin":
            base = os.path.join(
                os.path.expanduser("~/Library/Application Support"), APP_NAME
            )
        elif sys.platform.startswith("win"):
            root = os.environ.get("APPDATA") or os.path.expanduser("~")
            base = os.path.join(root, APP_NAME)
        else:  # Linux/other
            root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            base = os.path.join(root, APP_NAME)
    else:
        # Local/dev run: the project directory, matching the original relative paths.
        base = os.getcwd()
    os.makedirs(base, exist_ok=True)
    return base


def data_path(name: str) -> str:
    """Absolute path to `name` inside the app's data directory."""
    return os.path.join(data_dir(), name)
