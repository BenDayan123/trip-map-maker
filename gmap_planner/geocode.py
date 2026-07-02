"""Geocoding stage: resolve place names to exact coordinates."""

import json
import urllib.parse
import urllib.request

from .config import GEOCODE_URL
from .errors import PipelineError


# Geocoding API statuses that will fail for EVERY request (bad/missing key,
# quota, billing) — no point hammering the rest of the itinerary once seen.
_FATAL_GEOCODE_STATUSES = {"REQUEST_DENIED", "OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}


def geocode_place(name: str, geo_api_key: str) -> tuple[float, float] | None:
    """Convert a place name to coordinates via the Google Geocoding API.

    Returns (lat, lng), or None on any failure. Raises PipelineError for a
    fatal, itinerary-wide failure (bad key, quota) so the caller can stop and
    report which API failed instead of silently falling back for every place.
    """
    if not name:
        return None

    url = f"{GEOCODE_URL}?{urllib.parse.urlencode({'address': name, 'key': geo_api_key})}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ! Geocoding API request failed for {name!r}: {e}")
        return None

    status = payload.get("status")
    if status != "OK":
        message = payload.get("error_message", "")
        if status in _FATAL_GEOCODE_STATUSES:
            detail = f": {message}" if message else ""
            raise PipelineError(f"Geocoding API error [{status}]{detail}")
        if status not in ("ZERO_RESULTS", None):
            print(f"  ! Geocoding API error for {name!r}: {status} {message}".rstrip())
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
    locations = [loc for day in itinerary.get("days", [])
                 for loc in day.get("locations", [])]

    if not api_key:
        print("  ! Geocoding API skipped: no key provided "
              "(set GEO_API_KEY or pass --geo-api-key). Keeping Gemini's coordinates.")
        return 0, len(locations)

    corrected = fallback = 0
    for loc in locations:
        try:
            result = geocode_place(loc.get("name", ""), api_key)
        except PipelineError as e:
            # Fatal, itinerary-wide failure (bad key, quota): report which API
            # failed once and keep Gemini's coords for every remaining place.
            remaining = len(locations) - corrected - fallback
            print(f"  ! {e}\n    Keeping Gemini's coordinates for "
                  f"{remaining} remaining location(s).")
            return corrected, fallback + remaining
        if result:
            loc["lat"], loc["lng"] = result
            corrected += 1
        else:
            fallback += 1
    return corrected, fallback
