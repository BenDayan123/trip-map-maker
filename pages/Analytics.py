"""Analytics page: created-map log from the Google Sheet.

Streamlit auto-discovers files under ``pages/`` and adds them to the sidebar nav;
``streamlit_app.py`` stays the default "Create map" page. Open to read (no gate).

Column titles match the ones written to the Sheet (`analytics.COLUMNS`), so the
page and the Sheet read the same way.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from gmap_planner.analytics import (
    COLUMNS,
    _sheet_id,
    _worksheet,
    ensure_layout,
    fetch_rows,
    maps_in_row,
)

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

df = pd.DataFrame(rows)


def column(key: str) -> pd.Series:
    """A column of the log, empty-but-present if the Sheet never had it."""
    return df[key] if key in df else pd.Series([""] * len(df), index=df.index)


df["created_at"] = pd.to_datetime(column("created_at"), errors="coerce")
df["trip_name"] = column("trip_name").fillna("").astype(str)
df["map_links"] = column("map_links").fillna("").astype(str)
# Rows logged before the Maps column existed: count their links instead.
counted = df["map_links"].map(maps_in_row)
df["maps"] = pd.to_numeric(column("maps"), errors="coerce").fillna(counted).astype(int)
# Places were never recorded for older rows — nothing to reconstruct them from.
df["places"] = pd.to_numeric(column("places"), errors="coerce").fillna(0).astype(int)

# --- Metrics (same definitions as the Sheet's summary box) ---
this_month = df["created_at"].dt.to_period("M") == pd.Period(datetime.now(), freq="M")

c1, c2, c3 = st.columns(3)
c1.metric("Publishes", len(df))
c2.metric("Maps created", int(df["maps"].sum()))
c3.metric("Places created", int(df["places"].sum()))

c4, c5, c6 = st.columns(3)
c4.metric("Distinct trips", df["trip_name"].nunique())
c5.metric("Maps this month", int(df.loc[this_month, "maps"].sum()))
c6.metric("Places this month", int(df.loc[this_month, "places"].sum()))

# --- Over-time chart ---
by_day = (
    df.dropna(subset=["created_at"])
    .assign(day=lambda d: d["created_at"].dt.date)
    .groupby("day")
    .size()
    .rename("publishes")
)
if not by_day.empty:
    st.subheader("Publishes over time")
    st.bar_chart(by_day)

# --- Table (newest first) ---
st.subheader("Log")
titles = dict(COLUMNS)
table = (
    df.sort_values("created_at", ascending=False)
    .assign(map_links=lambda d: d["map_links"].str.split("\n"))
    .loc[:, [key for key, _ in COLUMNS]]
    .rename(columns=titles)
)
st.dataframe(
    table,
    width="stretch",
    hide_index=True,
    column_config={
        titles["created_at"]: st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
        titles["maps"]: st.column_config.NumberColumn(width="small"),
        titles["places"]: st.column_config.NumberColumn(width="small"),
        titles["map_links"]: st.column_config.ListColumn(width="large"),
    },
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
