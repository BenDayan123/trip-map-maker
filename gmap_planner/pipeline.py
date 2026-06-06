"""Pipeline orchestration: thin CLI wrapper over the shared service."""

import os
import sys

from dotenv import load_dotenv

from .cli import parse_args, resolve_api_key
from .errors import PipelineError
from .service import PipelineResult, run_pipeline


def print_summary(result: PipelineResult, layers_per_file: int) -> None:
    print(f"\nTrip: {result.trip_name}")
    print(f"Total days: {result.days}")
    print(f"Total locations: {result.locations}")
    print(f"Layers (days) per KML file: {layers_per_file}")
    print(f"Output folder: {result.output_dir}")
    print(f"KML files written ({len(result.files)}):")
    for p in result.files:
        print(f"  {p}")


def main() -> None:
    load_dotenv()
    args = parse_args()
    api_key = resolve_api_key(args)
    geo_api_key = args.geo_api_key or os.environ.get("GEO_API_KEY")

    try:
        result = run_pipeline(
            args.file,
            gemini_api_key=api_key,
            geo_api_key=geo_api_key,
            output_dir=args.output_dir,
            layers_per_file=args.layers_per_file,
            no_geocode=args.no_geocode,
            progress=lambda step, frac: print(f"[{int(frac * 100):3d}%] {step}..."),
        )
    except PipelineError as e:
        sys.exit(f"Error: {e}")

    print_summary(result, args.layers_per_file)
