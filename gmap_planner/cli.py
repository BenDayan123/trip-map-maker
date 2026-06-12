"""Command-line argument parsing and API-key resolution."""

import argparse
import os
import sys

from .config import DRIVE_CREDENTIALS_FILE, MAX_LAYERS_PER_FILE, PW_PROFILE_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse a travel itinerary (PDF/TXT) and generate KML layers + Google Maps URLs."
    )
    parser.add_argument("file", nargs="?", help="Path to the input itinerary file (.pdf or .txt)")
    parser.add_argument("--api-key", default=None, help="Gemini API key (falls back to GOOGLE_API_KEY in .env)")
    parser.add_argument("--geo-api-key", default=None, help="Geocoding API key (falls back to GEO_API_KEY in .env)")
    parser.add_argument("--output-dir", default="output", help="Directory to write output files (default: ./output)")
    parser.add_argument("--layers-per-file", type=int, default=MAX_LAYERS_PER_FILE,
                        help=f"Days (layers) per KML file (default/max: {MAX_LAYERS_PER_FILE}, the My Maps limit)")
    parser.add_argument("--no-geocode", action="store_true",
                        help="Skip the Geocoding API step (use Gemini's raw coordinates)")

    # --- My Maps automation + Drive sharing ---
    parser.add_argument("--login", action="store_true",
                        help="One-time headed Google login for My Maps, then exit. "
                             "Saves the session so later runs are headless.")
    parser.add_argument("--share", default=None, metavar="EMAILS",
                        help="Comma-separated emails to create + share a My Maps map with "
                             "(one map per KML file). Enables browser automation.")
    parser.add_argument("--share-role", default="reader",
                        help="Access for shared people: viewer/reader, commenter, editor/writer "
                             "(default: reader).")
    parser.add_argument("--headed", action="store_true",
                        help="Show the browser during automation (default: headless).")
    parser.add_argument("--no-notify", action="store_true",
                        help="Don't email people when sharing a map.")
    parser.add_argument("--profile-dir", default=PW_PROFILE_DIR,
                        help=f"Playwright Chromium profile dir (default: {PW_PROFILE_DIR}).")
    parser.add_argument("--credentials", default=DRIVE_CREDENTIALS_FILE,
                        help=f"Drive OAuth client file (default: {DRIVE_CREDENTIALS_FILE}).")
    args = parser.parse_args()

    if args.login:
        return args  # login mode needs no input file

    if not args.file:
        parser.error("the following arguments are required: file (or use --login)")
    if not os.path.isfile(args.file):
        sys.exit(f"Error: File not found: {args.file}")
    ext = os.path.splitext(args.file)[1].lower()
    if ext not in (".pdf", ".txt"):
        sys.exit(f"Error: Unsupported file type '{ext}'. Only .pdf and .txt are supported.")

    return args


def resolve_api_key(args: argparse.Namespace) -> str:
    key = args.api_key or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit(
            "Error: No API key provided. Add GOOGLE_API_KEY=... to a .env file or pass --api-key."
        )
    return key
