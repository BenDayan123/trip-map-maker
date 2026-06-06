"""Geocoding stage: resolve place names to exact coordinates."""

import json
import urllib.parse
import urllib.request

from .config import GEOCODE_URL


def geocode_place(name: str, geo_api_key: str) -> tuple[float, float] | None:
    """Convert a place name to coordinates via the Google Geocoding API.

    Returns (lat, lng), or None on any failure.
    """
    if not name:
        return None

    url = f"{GEOCODE_URL}?{urllib.parse.urlencode({'address': name, 'key': geo_api_key})}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ! Geocode failed for {name!r}: {e}")
        return None

    status = payload.get("status")
    if status != "OK":
        if status not in ("ZERO_RESULTS", None):
            print(f"  ! Geocode error for {name!r}: {status} {payload.get('error_message', '')}".rstrip())
        return None

    results = payload.get("results") or []
    if not results:
        return None
    loc = results[0].get("geometry", {}).get("location", {})
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None
    return lat, lng


def geocode_itinerary(itinerary: dict, api_key: str) -> tuple[int, int]:
    """Snap every location's coords to its exact Google Maps point in place.

    Falls back to Gemini's coords for any location that can't be resolved.
    Returns (corrected_count, fallback_count).
    """
    corrected = fallback = 0
    for day in itinerary.get("days", []):
        for loc in day.get("locations", []):
            result = geocode_place(loc.get("name", ""), api_key)
            if result:
                loc["lat"], loc["lng"] = result
                corrected += 1
            else:
                fallback += 1
    return corrected, fallback
