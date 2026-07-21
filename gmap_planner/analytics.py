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
    ("places", "Places"),
    ("map_links", "Map Links"),
]
KEYS = [key for key, _ in COLUMNS]
HEADER = [title for _, title in COLUMNS]


def _col_letter(index: int) -> str:
    """0-based column index as its A1 letter (the Sheet stays well under Z)."""
    return chr(ord("A") + index)


# Table occupies A..<end>; then one gutter column, then the summary's label/value
# pair. Derived from COLUMNS so adding a column shifts the whole layout for free.
_TABLE_END_COL = _col_letter(len(COLUMNS) - 1)
_LABEL_COL_INDEX = len(COLUMNS) + 1
_VALUE_COL_INDEX = _LABEL_COL_INDEX + 1
_C = {key: _col_letter(i) for i, key in enumerate(KEYS)}  # key -> its column letter

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


def places_in_kml(kml_path: str) -> int:
    """How many places (placemarks) a generated KML file contains.

    Counted from the file we just wrote rather than plumbed through the publish
    layer: the KML *is* the record of what landed on the map.
    """
    try:
        import xml.etree.ElementTree as ET

        ns = "{http://www.opengis.net/kml/2.2}"
        return sum(1 for _ in ET.parse(kml_path).iter(f"{ns}Placemark"))
    except Exception:
        return 0


def _safe_text(value: str) -> str:
    """Text that can't be swallowed as a formula when written as USER_ENTERED."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


# --- Sheet layout ---------------------------------------------------------
#
# The Sheet is the admin's read surface, so it's laid out like a small report:
# the table in A..<_TABLE_END_COL>, one gutter column, then a live summary. The
# summary is written as *formulas*, not values, so it stays right when rows are
# appended (by us or by hand) without another API round-trip.

BACKUP_SHEET_NAME = "Backup (pre-format)"

_MONTH_START = "EOMONTH(TODAY(),-1)+1"  # first day of the current month
_NEXT_MONTH = "EOMONTH(TODAY(),0)+1"    # first day of the next one
_DATE_COL = f"${_C['created_at']}$2:${_C['created_at']}"
_THIS_MONTH = f'{_DATE_COL},">="&{_MONTH_START},{_DATE_COL},"<"&{_NEXT_MONTH}'


def _total(key: str) -> str:
    col = f"${_C[key]}$2:${_C[key]}"
    return f"=SUM({col})"


def _month_total(key: str) -> str:
    col = f"${_C[key]}$2:${_C[key]}"
    return f"=SUMIFS({col},{_THIS_MONTH})"


_SUMMARY = [
    ("Summary", ""),  # title row
    ("Total publishes", f"=MAX(0,COUNTA({_DATE_COL}))"),
    ("Distinct trips",
     f"=IF(COUNTA(${_C['trip_name']}$2:${_C['trip_name']})=0,0,"
     f"COUNTUNIQUE(${_C['trip_name']}$2:${_C['trip_name']}))"),
    ("Maps created", _total("maps")),
    ("Places created", _total("places")),
    ("Maps this month", _month_total("maps")),
    ("Places this month", _month_total("places")),
    ("Publishes this month", f"=COUNTIFS({_THIS_MONTH})"),
    ("Latest publish",
     f'=IF(COUNT({_DATE_COL})=0,"—",TEXT(MAX({_DATE_COL}),"yyyy-mm-dd hh:mm"))'),
]

_TEAL = {"red": 0.059, "green": 0.463, "blue": 0.431}      # header fill
_WHITE = {"red": 1, "green": 1, "blue": 1}
_BAND = {"red": 0.953, "green": 0.976, "blue": 0.976}      # every other row
_TINT = {"red": 0.925, "green": 0.965, "blue": 0.957}      # summary box fill
_LINE = {"red": 0.784, "green": 0.855, "blue": 0.847}      # summary box border
# Column widths by canonical key; the gutter + summary pair follow the table.
_KEY_WIDTHS = {"created_at": 150, "trip_name": 220, "maps": 70, "places": 70,
               "map_links": 520}
_WIDTHS = {i: _KEY_WIDTHS[key] for i, key in enumerate(KEYS)}
_WIDTHS.update({len(KEYS): 24, _LABEL_COL_INDEX: 190, _VALUE_COL_INDEX: 110})


def _layout_requests(sheet_id: int, banding_id: int | None) -> list[dict]:
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
        # The count columns read better centred under their short titles.
        {"repeatCell": {
            "range": dict(body, startColumnIndex=KEYS.index("maps"),
                          endColumnIndex=KEYS.index("places") + 1),
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}},
        {"setBasicFilter": {"filter": {"range": dict(table, startRowIndex=0)}}},
    ]
    for index, width in _WIDTHS.items():
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": index, "endIndex": index + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    # Banding is a range object, not a cell format: an existing one has to be
    # *updated* (a second addBanding over the same rows is rejected), which also
    # widens it when a column is added to the table.
    banded = {"range": dict(table, startRowIndex=0),
              "rowProperties": {"headerColor": _TEAL,
                                "firstBandColor": _WHITE,
                                "secondBandColor": _BAND}}
    if banding_id is None:
        reqs.append({"addBanding": {"bandedRange": banded}})
    else:
        reqs.append({"updateBanding": {
            "bandedRange": dict(banded, bandedRangeId=banding_id), "fields": "*"}})
    # Summary box: bold labels, tinted title, a border around the whole thing.
    box = {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": len(_SUMMARY),
           "startColumnIndex": _LABEL_COL_INDEX, "endColumnIndex": _VALUE_COL_INDEX + 1}
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
            "range": dict(box, startRowIndex=1, endColumnIndex=_VALUE_COL_INDEX),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {
            "range": dict(box, startRowIndex=1, startColumnIndex=_VALUE_COL_INDEX),
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


def _migrated_rows(header: list[str], values: list[list[str]]) -> list[list]:
    """Existing rows re-shaped into the current `COLUMNS` order.

    Cells are matched by canonical key, so any earlier header shape lines up and
    a new column can be slotted in anywhere. `Maps` is backfilled by counting the
    links; a `Places` count nobody recorded stays blank rather than claiming 0.
    """
    keys = [_canonical(title) for title in header]
    rows = []
    for row in values:
        old = dict(zip(keys, row))
        # Rows alongside the summary box hold no log data — skipping them keeps a
        # backfilled count from inventing a phantom publish.
        if not any(old.get(k, "").strip() for k in ("created_at", "trip_name", "map_links")):
            continue
        links = old.get("map_links", "")
        new = []
        for key in KEYS:
            if key == "maps":
                new.append(old.get("maps") or maps_in_row(links))
            elif key == "map_links":
                new.append(links)
            else:
                new.append(_safe_text(old.get(key, "")))
        rows.append(new)
    return rows


def ensure_layout(ws) -> bool:
    """Make the Sheet readable: display header, summary box, formatting.

    Idempotent and best-effort — it costs one read when the Sheet is already
    laid out, and never raises (a Sheets problem must not break map generation).
    A Sheet on an older column set is migrated in place (after a backup copy).
    Returns True when the Sheet ended up laid out.
    """
    try:
        # One read covering the header row and the summary's label column. The
        # labels are checked in full, not just the title: the box shares rows with
        # the table, so deleting a log row in the browser shifts the labels up and
        # eats one — checking them all means the next call puts the box back.
        probe = ws.get(f"A1:{_col_letter(_VALUE_COL_INDEX)}{len(_SUMMARY)}")
        grid = [row + [""] * (_VALUE_COL_INDEX + 1 - len(row)) for row in probe]
        grid += [[""] * (_VALUE_COL_INDEX + 1)] * (len(_SUMMARY) - len(grid))
        first_row = grid[0]
        cell = (lambda i: first_row[i])
        labels = [row[_LABEL_COL_INDEX] for row in grid]
        if first_row[:len(HEADER)] == HEADER and labels == [lbl for lbl, _ in _SUMMARY]:
            return True  # already tidy

        spreadsheet = ws.spreadsheet
        if cell(0):
            # Existing log: rewrite the block so it matches the current columns
            # and the timestamps land as real dates.
            values = ws.get_all_values()
            _backup_once(spreadsheet, ws)
            data = _migrated_rows(values[0], values[1:])
            ws.update([HEADER] + data, "A1", value_input_option="USER_ENTERED")
        else:
            ws.update([HEADER], "A1", value_input_option="USER_ENTERED")

        # A summary box from an earlier column count sits one column to the left,
        # so clear the whole band right of the table before rewriting it.
        gutter = _col_letter(len(KEYS))
        ws.batch_clear([f"{gutter}1:{_col_letter(_VALUE_COL_INDEX + 2)}{len(_SUMMARY)}"])
        ws.update([list(pair) for pair in _SUMMARY],
                  f"{_col_letter(_LABEL_COL_INDEX)}1", value_input_option="USER_ENTERED")

        meta = spreadsheet.fetch_sheet_metadata()
        props = next((s for s in meta.get("sheets", [])
                      if s.get("properties", {}).get("sheetId") == ws.id), {})
        banding = (props.get("bandedRanges") or [{}])[0].get("bandedRangeId")
        spreadsheet.batch_update({"requests": _layout_requests(ws.id, banding)})
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
    """Append one row for a publish event: time, trip, map/place counts, links.

    `maps` is a list of `publish.PublishedMap`. Only maps with a live URL and no
    error are logged; a run with no successful map writes nothing. The place count
    is read from each map's KML file, so it's the number of pins that actually
    reached My Maps across all of this publish's maps. Never raises.
    """
    live = [m for m in maps if getattr(m, "url", "") and not getattr(m, "error", "")]
    if not live:
        return
    ws = _worksheet()
    if ws is None:
        return
    try:
        ensure_layout(ws)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        places = sum(places_in_kml(getattr(m, "file", "")) for m in live)
        # USER_ENTERED so the timestamp lands as a real date — the summary box's
        # month formulas compare against it. `table_range` pins the append to the
        # table columns: without it the summary box counts as data and rows land
        # underneath it, leaving a hole in the log.
        ws.append_row(
            [now, _safe_text(trip_name or "(unnamed)"), len(live), places,
             "\n".join(m.url for m in live)],
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

    Only the table columns are read (`A:{end}`) — the summary box to their right
    is presentation, and its cells would otherwise show up as unnamed headers.
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
        record = dict(zip(keys, row))
        if not record.get("created_at", "").strip():
            continue  # spacer row, or a stray cell next to the summary box
        for key in ("maps", "places"):  # counts read back as numbers
            if str(record.get(key, "")).isdigit():
                record[key] = int(record[key])
        rows.append(record)
    return rows
