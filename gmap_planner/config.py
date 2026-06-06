"""Shared constants and configuration."""

GEMINI_MODEL = "gemini-3.1-flash-lite"
# GEMINI_MODEL = "gemini-3.5-flash"

# Google My Maps allows at most 10 layers per map (one KML file = one map).
MAX_LAYERS_PER_FILE = 10

# Geocoding API — converts a place name/address to coordinates.
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Per-day pin colors (Material 700 shades; white number stays readable on each).
DAY_COLORS = [
    "0288D1", "D32F2F", "388E3C", "7B1FA2", "E65100", "00796B",
    "C2185B", "303F9F", "5D4037", "455A64", "0097A7", "827717",
]
