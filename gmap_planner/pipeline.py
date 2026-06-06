"""Pipeline orchestration: wires the stages together for the CLI."""

import os

from dotenv import load_dotenv
from google import genai

from .cli import parse_args, resolve_api_key
from .gemini import extract_itinerary, load_file_for_gemini
from .geocode import geocode_itinerary
from .kml import chunk_days, sanitize_folder_name, write_kml_files


def print_summary(itinerary: dict, trip_dir: str, layer_paths: list[str], layers_per_file: int) -> None:
    days = itinerary.get("days", [])
    total_locations = sum(len(d.get("locations", [])) for d in days)
    print(f"\nTrip: {itinerary.get('trip_name', '(unnamed)')}")
    print(f"Total days: {len(days)}")
    print(f"Total locations: {total_locations}")
    print(f"Layers (days) per KML file: {layers_per_file}")
    print(f"Output folder: {trip_dir}")
    print(f"KML files written ({len(layer_paths)}):")
    for p in layer_paths:
        print(f"  {p}")


def main() -> None:
    load_dotenv()
    args = parse_args()
    api_key = resolve_api_key(args)
    client = genai.Client(api_key=api_key)
    geo_api_key = args.geo_api_key or os.environ.get("GEO_API_KEY")

    parts, source = load_file_for_gemini(args.file, client)
    print(f"Loaded itinerary from: {source}")
    print("Extracting locations via Gemini...")

    itinerary = extract_itinerary(parts, client)
    days = itinerary.get("days", [])

    if not days:
        print("Warning: No days found in the extracted itinerary.")

    if not args.no_geocode and days:
        print("Converting place names to coordinates (Geocoding API)...")
        corrected, fallback = geocode_itinerary(itinerary, geo_api_key)
        print(f"  Corrected {corrected} location(s); {fallback} kept Gemini's estimate.")

    chunks = chunk_days(days, args.layers_per_file)

    # Each trip's KML files go into their own folder under the output dir.
    trip_folder = sanitize_folder_name(itinerary.get("trip_name", "Trip"))
    trip_dir = os.path.join(args.output_dir, trip_folder)
    os.makedirs(trip_dir, exist_ok=True)
    layer_paths = write_kml_files(chunks, trip_dir)
    print_summary(itinerary, trip_dir, layer_paths, args.layers_per_file)
