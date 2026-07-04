"""Shared constants and configuration."""

GEMINI_MODEL = "gemini-3.1-flash-lite"
# GEMINI_MODEL = "gemini-3.5-flash"

# Google My Maps allows at most 10 layers per map (one KML file = one map).
MAX_LAYERS_PER_FILE = 10

# Geocoding API — converts a place name/address to coordinates.
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Free-tier Geocoding quota for the usage gauge (override via secrets/env to match
# your actual Google quota). Resets monthly.
GEO_MONTHLY_LIMIT = 10000

# --- My Maps browser automation + Drive sharing -------------------------------
# My Maps has no create/import API, so a map is created by driving the My Maps
# editor with Playwright. Sharing then goes through the Drive API (a My Maps map
# is a Drive file of this mimeType).
MYMAPS_HOME_URL = "https://www.google.com/maps/d/?hl=en"
MYMAPS_MAP_MIME = "application/vnd.google-apps.map"
# Persistent files live in the app data dir: the project folder for a local run, or a
# stable per-user folder inside a packaged exe (where the cwd is a temp unpack dir).
from .paths import data_path  # noqa: E402

# Persistent Chromium profile so the one-time Google login is reused on every run.
PW_PROFILE_DIR = data_path(".pw-profile")
# OAuth client + cached token for the Drive sharing step (both gitignored).
DRIVE_CREDENTIALS_FILE = data_path("credentials.json")
DRIVE_TOKEN_FILE = data_path("token.json")
# Sharing a map created in the browser (not by this app) needs full Drive scope;
# the narrower drive.file scope only covers files the app itself created.
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
# Friendly --share-role values → Drive permission roles.
DRIVE_ROLE_ALIASES = {
    "viewer": "reader", "reader": "reader",
    "commenter": "commenter", "comment": "commenter",
    "editor": "writer", "writer": "writer",
}

# Per-day pin colors (Material 700 shades; white number stays readable on each).
DAY_COLORS = [
    "0288D1", "D32F2F", "388E3C", "7B1FA2", "E65100", "00796B",
    "C2185B", "303F9F", "5D4037", "455A64", "0097A7", "827717",
]
