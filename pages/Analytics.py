"""Analytics page: created-map log from the Google Sheet.

Streamlit auto-discovers files under ``pages/`` and adds them to the sidebar nav;
``streamlit_app.py`` stays the default "Create map" page. Open to read (no gate).

Column titles match the ones written to the Sheet (`analytics.COLUMNS`), so the
page and the Sheet read the same way.
"""

from datetime import datetime

import streamlit as st

from gmap_planner.analytics import _sheet_id, _worksheet, ensure_layout, fetch_rows, maps_in_row

st.set_page_config(page_title="Analytics", page_icon="📊", layout="centered")
st.title("📊 Analytics")

ws = _worksheet()
if ws is None:
    st.error(
        "Analytics storage isn't configured. Set the `GCP_SA_JSON` and "
        "`ANALYTICS_SHEET_ID` secrets, share the Sheet with the service account's "
        "email, and enable the Google Sheets API."
    )
    st.stop()

rows = fetch_rows()
if not rows:
    st.info("No maps have been logged yet. Publish a map to see it here.")
    st.stop()


def maps_count(row: dict) -> int:
    """Row's `maps` count, falling back to counting `map_links` (older rows)."""
    maps = row.get("maps")
    return int(maps) if maps else maps_in_row(row.get("map_links", ""))


def places_count(row: dict) -> int:
    places = row.get("places")
    return int(places) if places else 0


this_month_prefix = datetime.now().strftime("%Y-%m")
this_month_rows = [r for r in rows if r.get("created_at", "").startswith(this_month_prefix)]

# --- Metrics (same definitions as the Sheet's summary box) ---
c1, c2, c3 = st.columns(3)
c1.metric("Publishes", len(rows))
c2.metric("Maps created", sum(maps_count(r) for r in rows))
c3.metric("Places created", sum(places_count(r) for r in rows))

c4, c5, c6 = st.columns(3)
c4.metric("Distinct trips", len({r.get("trip_name", "") for r in rows}))
c5.metric("Maps this month", sum(maps_count(r) for r in this_month_rows))
c6.metric("Places this month", sum(places_count(r) for r in this_month_rows))

# --- Log (newest first) ---
st.subheader("Log")
for row in sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True):
    links = [line for line in row.get("map_links", "").splitlines() if line.strip()]
    link_md = " · ".join(f"[Map {i + 1}]({url})" for i, url in enumerate(links)) or "—"
    st.markdown(
        f"**{row.get('trip_name') or '(unnamed)'}** — {row.get('created_at', '')}  \n"
        f"{maps_count(row)} map(s), {places_count(row)} place(s) — {link_md}"
    )

sheet_id = _sheet_id()
left, right = st.columns([3, 1])
if sheet_id:
    left.caption(
        f"Source: [Google Sheet](https://docs.google.com/spreadsheets/d/{sheet_id})"
    )
# One-click upgrade for a Sheet that predates the current layout (a publish does
# this too, but the admin shouldn't have to make a map to tidy the Sheet).
if right.button("Tidy up the Sheet", help="Apply the header, styling and summary box"):
    if ensure_layout(ws):
        st.success("The Sheet is formatted and the summary box is up to date.")
    else:
        st.warning("Couldn't format the Sheet — check the service account's access.")
