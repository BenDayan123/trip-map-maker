"""Admin-only Analytics page: created-map log from the Google Sheet.

Streamlit auto-discovers files under ``pages/`` and adds them to the sidebar nav;
``Home.py`` stays the default "Create map" page. Gated behind an
``ADMIN_PASSWORD`` secret so only the admin sees the log.
"""

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from gmap_planner.analytics import _secret, _sheet_id, _worksheet, fetch_rows

st.set_page_config(page_title="Analytics", page_icon="📊", layout="centered")
st.title("📊 Analytics")


def require_admin() -> None:
    """Block the page unless the admin password matches. Stops the run otherwise."""
    password = _secret("ADMIN_PASSWORD")
    if not password:
        st.warning(
            "Analytics is locked but no `ADMIN_PASSWORD` secret is set. Add one to "
            "`st.secrets` to open this page."
        )
        st.stop()
    if st.session_state.get("is_admin"):
        return
    entered = st.text_input("Admin password", type="password")
    if not entered:
        st.stop()
    if entered != password:
        st.error("Wrong password.")
        st.stop()
    st.session_state["is_admin"] = True


require_admin()

if _worksheet() is None:
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
df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

# --- Metrics ---
total = len(df)
trips = df["trip_name"].nunique() if "trip_name" in df else 0
week_ago = datetime.now() - timedelta(days=7)
last_7 = int((df["created_at"] >= week_ago).sum())

c1, c2, c3 = st.columns(3)
c1.metric("Publishes logged", total)
c2.metric("Distinct trips", trips)
c3.metric("Last 7 days", last_7)

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
st.dataframe(
    df.sort_values("created_at", ascending=False),
    use_container_width=True,
    hide_index=True,
)

sheet_id = _sheet_id()
if sheet_id:
    st.caption(
        f"Source: [Google Sheet](https://docs.google.com/spreadsheets/d/{sheet_id})"
    )
