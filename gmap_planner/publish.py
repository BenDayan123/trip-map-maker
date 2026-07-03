"""Orchestrate the autonomous step: KML files -> My Maps maps -> shared with people.

One KML file becomes one My Maps map (the per-file grouping decision). Each map is
then shared with the requested recipients via the Drive API. Returns one record per
file so the CLI can print the live map URLs.
"""

import os
from dataclasses import dataclass, field
from typing import Callable

from .config import PW_PROFILE_DIR
from .drive_share import get_drive_service, share_map
from .mymaps import MyMapsSession

ProgressFn = Callable[[str, float], None]


@dataclass
class PublishedMap:
    file: str
    title: str
    url: str = ""
    mid: str = ""
    shared_with: list[str] = field(default_factory=list)
    error: str = ""


def _title_for(kml_path: str, trip_name: str) -> str:
    """Map title: '<trip> — Day(s) N' derived from the KML filename (e.g. 1-10.kml)."""
    stem = os.path.splitext(os.path.basename(kml_path))[0]
    span = f"Days {stem}" if "-" in stem else f"Day {stem}"
    return f"{trip_name} — {span}" if trip_name else span


def publish_kml_files(
    kml_files: list[str],
    *,
    trip_name: str,
    recipients: list[str],
    role: str = "reader",
    profile_dir: str = PW_PROFILE_DIR,
    headless: bool = True,
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
    notify: bool = True,
    storage_state=None,
    progress: ProgressFn | None = None,
) -> list[PublishedMap]:
    """Create one shared My Maps map per KML file. Never raises — per-file errors
    are captured on each ``PublishedMap.error`` so one bad file can't abort the rest.

    `storage_state`, when given (dict / JSON string / path), runs the browser headless
    from a captured signed-in session instead of the local persistent profile — the
    path used on a headless host (Streamlit Community Cloud).
    """
    def report(step: str, frac: float) -> None:
        if progress:
            progress(step, frac)

    # Authenticate Drive up front (one consent) so we fail fast before the browser.
    drive = get_drive_service(credentials_path, token_path) if recipients else None

    results: list[PublishedMap] = []
    total = len(kml_files)
    with MyMapsSession(
        profile_dir=profile_dir, headless=headless, storage_state=storage_state
    ) as session:
        for i, kml in enumerate(kml_files):
            title = _title_for(kml, trip_name)
            rec = PublishedMap(file=kml, title=title)
            report(f"Creating map {i + 1}/{total}: {title}", (i + 0.3) / total)
            try:
                info = session.create_map_from_kml(kml, title)
                rec.url, rec.mid = info["url"], info["mid"]
                if recipients:
                    report(f"Sharing map {i + 1}/{total}", (i + 0.7) / total)
                    rec.shared_with = share_map(
                        rec.mid, recipients, role,
                        title=title, service=drive, notify=notify,
                    )
            except Exception as e:  # capture, keep going
                rec.error = str(e)
            results.append(rec)
    report("Done", 1.0)
    return results
