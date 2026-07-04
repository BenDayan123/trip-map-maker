"""Analytics log: append each My Maps publish to a Google Sheet.

Map creation runs locally (needs a browser), but the Sheet is hosted by Google,
so it survives Streamlit Community Cloud redeploys and is readable from the
hosted app. The admin can also view/edit the data directly in the browser.

Everything here is best-effort: any failure logs a warning and returns quietly
so a Sheets problem can never break map generation. Auth reuses the same
`GCP_SA_JSON` service account already used for the usage gauges — grant it Editor
on the target Sheet and enable the Google Sheets API.

Secrets/env used:
- ``GCP_SA_JSON``        service-account JSON (string)
- ``ANALYTICS_SHEET_ID`` id (or full URL) of the target Sheet

Header (this iteration, extensible): created_at, trip_name, map_links.
"""

import json
import os
from datetime import datetime

HEADER = ["created_at", "trip_name", "map_links"]

# gspread needs Sheets (read/write) + Drive (open-by-key) scopes.
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _secret(name: str) -> str | None:
    """Value from Streamlit secrets, then env, then the saved config.json.

    The config.json fallback is what makes the packaged exe work: it has no
    secrets.toml, so the admin enters these on the Setup page instead.
    """
    try:
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass  # no secrets.toml / streamlit not running — fall back below
    val = os.environ.get(name)
    if val:
        return val
    try:
        from gmap_planner.appconfig import load_app_config

        return load_app_config().get(name)
    except Exception:
        return None


def _sheet_id() -> str | None:
    """The Sheet id, accepting either a bare id or a full spreadsheet URL."""
    raw = _secret("ANALYTICS_SHEET_ID")
    if not raw:
        return None
    raw = raw.strip()
    marker = "/spreadsheets/d/"
    if marker in raw:
        return raw.split(marker, 1)[1].split("/", 1)[0]
    return raw


def _worksheet():
    """First worksheet of the analytics Sheet, or None if unconfigured/unreachable."""
    sa_json = _secret("GCP_SA_JSON")
    sheet_id = _sheet_id()
    if not sa_json or not sheet_id:
        return None
    try:
        import gspread
        from google.oauth2 import service_account

        sa_info = json.loads(sa_json) if isinstance(sa_json, str) else dict(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=_SCOPES
        )
        client = gspread.authorize(creds)
        return client.open_by_key(sheet_id).sheet1
    except PermissionError:
        # gspread wraps a 403 as an empty-message PermissionError.
        email = _client_email(sa_json)
        print(
            "  ! Analytics Sheet unavailable [403 permission]: share the Sheet "
            f"(Editor) with {email or 'the service account'} and enable the "
            "Google Sheets API on its project."
        )
        return None
    except Exception as e:
        detail = str(e) or repr(e)
        print(f"  ! Analytics Sheet unavailable [{type(e).__name__}]: {detail}")
        return None


def _client_email(sa_json) -> str | None:
    """Service-account email from the SA JSON, for actionable error messages."""
    try:
        info = json.loads(sa_json) if isinstance(sa_json, str) else dict(sa_json)
        return info.get("client_email")
    except Exception:
        return None


def _ensure_header(ws) -> None:
    """Write the header row if the sheet is empty."""
    try:
        if not ws.acell("A1").value:
            ws.update("A1", [HEADER])
    except Exception as e:
        print(f"  ! Analytics header check failed: {e}")


def record_publish(trip_name: str, maps) -> None:
    """Append one row for a publish event: its time, trip, and all live map links.

    `maps` is a list of `publish.PublishedMap`. Only maps with a live URL and no
    error are logged; a run with no successful map writes nothing. Never raises.
    """
    urls = [m.url for m in maps if getattr(m, "url", "") and not getattr(m, "error", "")]
    if not urls:
        return
    ws = _worksheet()
    if ws is None:
        return
    try:
        _ensure_header(ws)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([now, trip_name or "(unnamed)", "\n".join(urls)])
    except Exception as e:
        print(f"  ! Failed to log publish to the analytics Sheet: {e}")


def fetch_rows() -> list[dict]:
    """All logged rows as dicts (header → value), newest last. [] if unavailable."""
    ws = _worksheet()
    if ws is None:
        return []
    try:
        return ws.get_all_records()
    except Exception as e:
        print(f"  ! Failed to read the analytics Sheet: {e}")
        return []
