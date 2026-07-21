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

The Sheet is meant to be *read* by a human in the browser, so `ensure_layout`
also styles it: display column titles ("Created At", not "created_at"), a frozen
bold header, banded rows, sensible widths and a live summary box to the right of
the table. Add a column by extending ``COLUMNS`` (canonical key → display title)
and the row built in `record_publish`; older, shorter rows are tolerated.
"""

import json
import os
import re
from datetime import datetime

# Canonical key (used in code) -> display title (written to the Sheet).
COLUMNS = [
    ("created_at", "Created At"),
    ("trip_name", "Trip Name"),
    ("maps", "Maps"),
    ("map_links", "Map Links"),
]
HEADER = [title for _, title in COLUMNS]
_LEGACY_HEADER = ["created_at", "trip_name", "map_links"]
# Last column letter of the table itself (the summary box lives further right).
_TABLE_END_COL = chr(ord("A") + len(COLUMNS) - 1)

# gspread needs Sheets (read/write) + Drive (open-by-key) scopes.
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _secret(name: str) -> str | None:
    """Value from the saved config.json first, then Streamlit secrets, then env.

    config.json (the Setup page) is the admin's source of truth in the local /
    packaged app, so it wins over a stale secrets.toml — matches appconfig.get_secret.
    """
    try:
        from gmap_planner.appconfig import load_app_config

        val = load_app_config().get(name)
        if val:
            return val
    except Exception:
        pass  # streamlit/appconfig not importable — fall back below
    try:
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


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
    """The log worksheet, or None if unconfigured/unreachable.

    The first tab that isn't the migration backup — picking by index alone would
    hand back `Backup (pre-format)` once that tab exists.
    """
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
        tabs = client.open_by_key(sheet_id).worksheets()
        return next((w for w in tabs if w.title != BACKUP_SHEET_NAME), tabs[0])
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


def maps_in_row(links: str) -> int:
    """How many maps a `Map Links` cell holds (one URL per line)."""
    if not links:
        return 0
    return sum(1 for line in str(links).splitlines() if line.strip().startswith("http"))


def _safe_text(value: str) -> str:
    """Text that can't be swallowed as a formula when written as USER_ENTERED."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


# --- Sheet layout ---------------------------------------------------------
#
# The Sheet is the admin's read surface, so it's laid out like a small report:
# the table in A:D, a gutter in E, and a live summary in F:G. The summary is
# written as *formulas*, not values, so it stays right when rows are appended
# (by us or by hand) without another API round-trip.

BACKUP_SHEET_NAME = "Backup (pre-format)"

_MONTH_START = "EOMONTH(TODAY(),-1)+1"  # first day of the current month
_NEXT_MONTH = "EOMONTH(TODAY(),0)+1"    # first day of the next one
_SUMMARY = [
    ("Summary", ""),  # title row
    ("Total publishes", "=MAX(0,COUNTA($A$2:$A))"),
    ("Distinct trips", "=IF(COUNTA($B$2:$B)=0,0,COUNTUNIQUE($B$2:$B))"),
    ("Maps created", "=SUM($C$2:$C)"),
    ("Maps this month", f'=SUMIFS($C$2:$C,$A$2:$A,">="&{_MONTH_START},$A$2:$A,"<"&{_NEXT_MONTH})'),
    ("Publishes this month", f'=COUNTIFS($A$2:$A,">="&{_MONTH_START},$A$2:$A,"<"&{_NEXT_MONTH})'),
    ("Latest publish", '=IF(COUNT($A$2:$A)=0,"—",TEXT(MAX($A$2:$A),"yyyy-mm-dd hh:mm"))'),
]

_TEAL = {"red": 0.059, "green": 0.463, "blue": 0.431}      # header fill
_WHITE = {"red": 1, "green": 1, "blue": 1}
_BAND = {"red": 0.953, "green": 0.976, "blue": 0.976}      # every other row
_TINT = {"red": 0.925, "green": 0.965, "blue": 0.957}      # summary box fill
_LINE = {"red": 0.784, "green": 0.855, "blue": 0.847}      # summary box border
# Column widths, by 0-based index: A..D table, E gutter, F/G summary.
_WIDTHS = {0: 150, 1: 220, 2: 70, 3: 520, 4: 24, 5: 190, 6: 110}


def _layout_requests(sheet_id: int, has_banding: bool) -> list[dict]:
    """The batch_update requests that turn a bare grid into the report layout."""
    table = {"sheetId": sheet_id, "startColumnIndex": 0, "endColumnIndex": len(HEADER)}
    body = dict(table, startRowIndex=1)  # everything below the header
    reqs = [
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {
            "range": dict(table, startRowIndex=0, endRowIndex=1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _TEAL,
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "CLIP",
                "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": _WHITE}}},
            "fields": "userEnteredFormat(backgroundColor,verticalAlignment,wrapStrategy,textFormat)"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 34}, "fields": "pixelSize"}},
        # Real datetimes in A (the month formulas depend on it), links clipped so
        # a multi-map cell doesn't stretch the row.
        {"repeatCell": {
            "range": dict(body, startColumnIndex=0, endColumnIndex=1),
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "DATE_TIME", "pattern": "yyyy-mm-dd hh:mm"}}},
            "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {
            "range": body,
            "cell": {"userEnteredFormat": {
                "verticalAlignment": "TOP", "wrapStrategy": "CLIP"}},
            "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)"}},
        {"repeatCell": {
            "range": dict(body, startColumnIndex=2, endColumnIndex=3),
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}},
        {"setBasicFilter": {"filter": {"range": dict(table, startRowIndex=0)}}},
    ]
    for index, width in _WIDTHS.items():
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": index, "endIndex": index + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    if not has_banding:
        reqs.append({"addBanding": {"bandedRange": {
            "range": dict(table, startRowIndex=0),
            "rowProperties": {"headerColor": _TEAL,
                              "firstBandColor": _WHITE,
                              "secondBandColor": _BAND}}}})
    # Summary box: bold labels, tinted title, a border around the whole thing.
    box = {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": len(_SUMMARY),
           "startColumnIndex": 5, "endColumnIndex": 7}
    reqs += [
        {"repeatCell": {
            "range": box,
            "cell": {"userEnteredFormat": {"backgroundColor": _TINT}},
            "fields": "userEnteredFormat.backgroundColor"}},
        {"repeatCell": {
            "range": dict(box, endRowIndex=1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _TEAL,
                "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": _WHITE}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"repeatCell": {
            "range": dict(box, startRowIndex=1, endColumnIndex=6),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {
            "range": dict(box, startRowIndex=1, startColumnIndex=6),
            "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT"}},
            "fields": "userEnteredFormat.horizontalAlignment"}},
        {"updateBorders": {
            "range": box,
            "top": {"style": "SOLID", "color": _LINE},
            "bottom": {"style": "SOLID", "color": _LINE},
            "left": {"style": "SOLID", "color": _LINE},
            "right": {"style": "SOLID", "color": _LINE},
            "innerHorizontal": {"style": "SOLID", "color": _LINE}}},
    ]
    return reqs


def _migrated_rows(values: list[list[str]]) -> list[list]:
    """Old 3-column rows (`created_at, trip_name, map_links`) in the new shape.

    The `Maps` count is backfilled from the links cell; rows that pre-date real
    links (an early row holds a title, not URLs) simply come out as 0.
    """
    rows = []
    for row in values:
        created, trip, links = (row + ["", "", ""])[:3]
        rows.append([_safe_text(created), _safe_text(trip), maps_in_row(links), links])
    return rows


def ensure_layout(ws) -> bool:
    """Make the Sheet readable: display header, summary box, formatting.

    Idempotent and best-effort — it costs one read when the Sheet is already
    laid out, and never raises (a Sheets problem must not break map generation).
    Returns True when the Sheet ended up laid out.
    """
    try:
        head = ws.get("A1:G1")
        first_row = head[0] if head else []
        cell = (lambda i: first_row[i] if len(first_row) > i else "")
        if cell(0) == HEADER[0] and cell(5) == _SUMMARY[0][0]:
            return True  # already tidy

        spreadsheet = ws.spreadsheet
        if cell(0) in (_LEGACY_HEADER[0], HEADER[0]):
            # Existing log: rewrite the block so timestamps become real dates and
            # (for the legacy 3-column shape) the Maps column is inserted at C.
            values = ws.get_all_values()
            data = values[1:] if values else []
            if cell(0) == _LEGACY_HEADER[0] and data:
                _backup_once(spreadsheet, ws)
                data = _migrated_rows(data)
            ws.update([HEADER] + data, "A1", value_input_option="USER_ENTERED")
        else:
            ws.update([HEADER], "A1", value_input_option="USER_ENTERED")

        ws.update([list(pair) for pair in _SUMMARY], "F1", value_input_option="USER_ENTERED")

        meta = spreadsheet.fetch_sheet_metadata()
        props = next((s for s in meta.get("sheets", [])
                      if s.get("properties", {}).get("sheetId") == ws.id), {})
        spreadsheet.batch_update({
            "requests": _layout_requests(ws.id, bool(props.get("bandedRanges")))
        })
        return True
    except Exception as e:
        detail = str(e) or repr(e)
        print(f"  ! Analytics Sheet layout skipped [{type(e).__name__}]: {detail}")
        return False


def _backup_once(spreadsheet, ws) -> None:
    """Copy the sheet before the one-time migration rewrites it."""
    try:
        tabs = spreadsheet.worksheets()
        if BACKUP_SHEET_NAME not in [w.title for w in tabs]:
            # Last, so the log stays the first tab someone opens.
            spreadsheet.duplicate_sheet(
                ws.id, insert_sheet_index=len(tabs), new_sheet_name=BACKUP_SHEET_NAME
            )
    except Exception as e:
        print(f"  ! Analytics backup tab not created: {e}")


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
        ensure_layout(ws)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # USER_ENTERED so the timestamp lands as a real date — the summary box's
        # month formulas compare against it. `table_range` pins the append to the
        # A:D table: without it the summary box in F counts as data and rows land
        # underneath it, leaving a hole in the log.
        ws.append_row(
            [now, _safe_text(trip_name or "(unnamed)"), len(urls), "\n".join(urls)],
            value_input_option="USER_ENTERED",
            table_range=f"A1:{_TABLE_END_COL}1",
        )
    except Exception as e:
        print(f"  ! Failed to log publish to the analytics Sheet: {e}")


def _canonical(title: str) -> str:
    """A header cell as a stable key: "Created At" and "created_at" both match."""
    return re.sub(r"[^a-z0-9]+", "_", str(title).strip().lower()).strip("_")


def fetch_rows() -> list[dict]:
    """All logged rows as dicts keyed by canonical name, newest last.

    Keys are normalized (`Created At` → `created_at`) so callers work against
    either the display header or a Sheet still on the old snake_case one; rows
    written before a column existed simply lack that key. [] if unavailable.

    Only the table columns are read (`A:D`) — the summary box to their right is
    presentation, and its cells would otherwise show up as unnamed headers.
    """
    ws = _worksheet()
    if ws is None:
        return []
    try:
        values = ws.get_values(f"A1:{_TABLE_END_COL}")
    except Exception as e:
        print(f"  ! Failed to read the analytics Sheet: {e}")
        return []
    if not values:
        return []
    keys = [_canonical(title) for title in values[0]]
    rows = []
    for row in values[1:]:
        if not any(cell.strip() for cell in row):
            continue  # blank spacer row
        record = dict(zip(keys, row))
        if record.get("maps", "").isdigit():
            record["maps"] = int(record["maps"])
        rows.append(record)
    return rows
