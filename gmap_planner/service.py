"""Programmatic pipeline entry point, reused by the CLI and the GUI.

`run_pipeline` runs all stages and reports progress via an optional callback,
returning a `PipelineResult`. It raises `PipelineError` (never exits) so callers
own how failures are presented.
"""

import os
from dataclasses import dataclass, field
from typing import Callable

from google import genai

from .config import MAX_LAYERS_PER_FILE
from .errors import PipelineError
from .gemini import extract_itinerary, load_file_for_gemini
from .geocode import geocode_itinerary
from .kml import chunk_days, sanitize_folder_name, write_kml_files

# progress(step_label, fraction_0_to_1)
ProgressFn = Callable[[str, float], None]


@dataclass
class PipelineResult:
    trip_name: str
    days: int
    locations: int
    corrected: int
    fallback: int
    files: list[str] = field(default_factory=list)
    output_dir: str = ""


def run_pipeline(
    file_path: str,
    *,
    gemini_api_key: str,
    geo_api_key: str | None,
    output_dir: str,
    layers_per_file: int = MAX_LAYERS_PER_FILE,
    no_geocode: bool = False,
    progress: ProgressFn | None = None,
) -> PipelineResult:
    """Run the full itinerary→KML pipeline. Raises PipelineError on failure."""

    def report(step: str, frac: float) -> None:
        if progress:
            progress(step, frac)

    if not gemini_api_key:
        raise PipelineError("No Gemini API key provided.")

    client = genai.Client(api_key=gemini_api_key)

    report("Loading itinerary file", 0.1)
    parts, _source = load_file_for_gemini(file_path, client)

    report("Extracting locations with Gemini", 0.35)
    itinerary = extract_itinerary(parts, client)
    days = itinerary.get("days", [])
    if not days:
        raise PipelineError("No days found in the extracted itinerary.")

    corrected = fallback = 0
    if not no_geocode:
        report("Snapping place names to exact coordinates", 0.6)
        corrected, fallback = geocode_itinerary(itinerary, geo_api_key)

    report("Writing KML files", 0.85)
    chunks = chunk_days(days, layers_per_file)
    trip_folder = sanitize_folder_name(itinerary.get("trip_name", "Trip"))
    trip_dir = os.path.join(output_dir, trip_folder)
    os.makedirs(trip_dir, exist_ok=True)
    files = write_kml_files(chunks, trip_dir)

    report("Done", 1.0)
    return PipelineResult(
        trip_name=itinerary.get("trip_name", "(unnamed)"),
        days=len(days),
        locations=sum(len(d.get("locations", [])) for d in days),
        corrected=corrected,
        fallback=fallback,
        files=files,
        output_dir=trip_dir,
    )
