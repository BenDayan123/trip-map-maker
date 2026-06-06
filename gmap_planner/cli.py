"""Command-line argument parsing and API-key resolution."""

import argparse
import os
import sys

from .config import MAX_LAYERS_PER_FILE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse a travel itinerary (PDF/TXT) and generate KML layers + Google Maps URLs."
    )
    parser.add_argument("file", help="Path to the input itinerary file (.pdf or .txt)")
    parser.add_argument("--api-key", default=None, help="Gemini API key (falls back to GOOGLE_API_KEY in .env)")
    parser.add_argument("--geo-api-key", default=None, help="Geocoding API key (falls back to GEO_API_KEY in .env)")
    parser.add_argument("--output-dir", default="output", help="Directory to write output files (default: ./output)")
    parser.add_argument("--layers-per-file", type=int, default=MAX_LAYERS_PER_FILE,
                        help=f"Days (layers) per KML file (default/max: {MAX_LAYERS_PER_FILE}, the My Maps limit)")
    parser.add_argument("--no-geocode", action="store_true",
                        help="Skip the Geocoding API step (use Gemini's raw coordinates)")
    args = parser.parse_args()

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
