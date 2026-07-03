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


def _progress(step: str, frac: float) -> None:
    print(f"[{int(frac * 100):3d}%] {step}...")


def _publish(args, result: PipelineResult) -> None:
    """Create + share one My Maps map per KML file, then print the live URLs."""
    from .publish import publish_kml_files

    recipients = [e.strip() for e in args.share.split(",") if e.strip()]
    print(f"\nPublishing {len(result.files)} map(s) to My Maps "
          f"(share with: {', '.join(recipients) or 'no one'})...")
    maps = publish_kml_files(
        result.files,
        trip_name=result.trip_name,
        recipients=recipients,
        role=args.share_role,
        profile_dir=args.profile_dir,
        headless=not args.headed,
        credentials_path=args.credentials,
        notify=not args.no_notify,
        progress=_progress,
    )
    print("\nMy Maps results:")
    for m in maps:
        if m.error:
            print(f"  ✗ {m.title}: {m.error}")
        else:
            who = ", ".join(m.shared_with) if m.shared_with else "not shared"
            print(f"  ✓ {m.title}\n      {m.url}\n      shared with: {who}")


def main() -> None:
    load_dotenv()
    args = parse_args()

    if args.login:
        from .mymaps import login
        try:
            login(args.profile_dir)
        except PipelineError as e:
            sys.exit(f"Error: {e}")
        return

    if args.export_session:
        from .mymaps import export_session
        try:
            out = export_session(args.profile_dir)
        except PipelineError as e:
            sys.exit(f"Error: {e}")
        print(
            f"\nPaste the contents of {out} into your app's GOOGLE_STORAGE_STATE "
            "secret to let a hosted (headless) deployment publish while signed in."
        )
        return

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
            progress=_progress,
        )
    except PipelineError as e:
        sys.exit(f"Error: {e}")

    print_summary(result, args.layers_per_file)

    if args.share is not None:
        try:
            _publish(args, result)
        except PipelineError as e:
            sys.exit(f"Error: {e}")
