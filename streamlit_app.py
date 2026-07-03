"""Streamlit GUI for the itinerary → Google My Maps KML planner.

Run locally:   streamlit run streamlit_app.py
Hosted:        deploy to Streamlit Community Cloud (or any host) and set the
               GOOGLE_API_KEY / GEO_API_KEY secrets.

API keys are read from st.secrets first, then environment variables, so the same
code works hosted and locally. Admins normally never see or enter keys.
"""

import io
import json
import os
import tempfile
import zipfile

import streamlit as st

from gmap_planner.config import (
    DRIVE_CREDENTIALS_FILE,
    GEMINI_DAILY_LIMIT,
    GEO_MONTHLY_LIMIT,
    MAX_LAYERS_PER_FILE,
)
from gmap_planner.errors import PipelineError
from gmap_planner.mymaps import is_logged_in, login
from gmap_planner.publish import publish_kml_files
from gmap_planner.service import run_pipeline
from gmap_planner.usage import get_api_usage

MAX_UPLOAD_MB = 15

st.set_page_config(page_title="Trip Map Maker", page_icon="🗺️", layout="centered")


def get_secret(name: str) -> str | None:
    """Key from Streamlit secrets, falling back to environment variables."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass  # no secrets.toml present (e.g. local dev) — fall back to env
    return os.environ.get(name)


def ring_svg(pct: float, center: str, sub: str, color: str) -> str:
    """Dependency-free circular progress gauge as inline SVG."""
    import math

    r = 54
    circ = 2 * math.pi * r
    offset = circ * (1 - max(min(pct, 100), 0) / 100)
    return f"""
    <div style="text-align:center">
      <svg width="140" height="140" viewBox="0 0 140 140">
        <circle cx="70" cy="70" r="{r}" fill="none" stroke="#eceff1" stroke-width="12"/>
        <circle cx="70" cy="70" r="{r}" fill="none" stroke="{color}" stroke-width="12"
                stroke-linecap="round" stroke-dasharray="{circ:.1f}"
                stroke-dashoffset="{offset:.1f}" transform="rotate(-90 70 70)"/>
        <text x="70" y="72" text-anchor="middle" dominant-baseline="middle"
              font-size="26" font-weight="700" fill="#263238">{center}</text>
      </svg>
      <div style="color:#607d8b;font-size:0.85rem;margin-top:-6px">{sub}</div>
    </div>
    """


def _gauge_color(pct: float) -> str:
    if pct >= 90:
        return "#D32F2F"
    if pct >= 70:
        return "#E65100"
    return "#388E3C"


@st.cache_data(ttl=300, show_spinner=False)
def _cached_usage(project_id, sa_json, gem_limit, geo_limit):
    if not project_id or not sa_json:
        return None
    try:
        sa_info = json.loads(sa_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return get_api_usage(
        project_id=project_id,
        sa_info=sa_info,
        gemini_daily_limit=int(gem_limit),
        geo_monthly_limit=int(geo_limit),
    )


def render_usage_gauges() -> None:
    usage = _cached_usage(
        get_secret("GCP_PROJECT_ID"),
        get_secret("GCP_SA_JSON"),
        get_secret("GEMINI_DAILY_LIMIT") or GEMINI_DAILY_LIMIT,
        get_secret("GEO_MONTHLY_LIMIT") or GEO_MONTHLY_LIMIT,
    )
    if usage is None:
        st.caption("📊 API usage metrics not configured.")
        with st.expander("Enable the usage gauges"):
            st.markdown(
                "Set these secrets (needs the Cloud Monitoring API enabled and a "
                "service account with `roles/monitoring.viewer`):\n"
                "- `GCP_PROJECT_ID` — the project behind your API keys\n"
                "- `GCP_SA_JSON` — the service-account JSON (as a string)\n"
                "- `GEMINI_DAILY_LIMIT`, `GEO_MONTHLY_LIMIT` — your quota numbers"
            )
        return

    g, geo = usage["gemini"], usage["geocode"]
    st.markdown(
        ring_svg(g["pct"], f"{g['pct']:.0f}%",
                 f"Gemini · today<br>{g['used']:,} / {g['limit']:,}",
                 _gauge_color(g["pct"])),
        unsafe_allow_html=True,
    )
    st.markdown(
        ring_svg(geo["pct"], f"{geo['pct']:.0f}%",
                 f"Geocoding · this month<br>{geo['used']:,} / {geo['limit']:,}",
                 _gauge_color(geo["pct"])),
        unsafe_allow_html=True,
    )


# --- Header ---------------------------------------------------------------
st.title("🗺️ Trip Map Maker")
st.caption(
    "Upload a travel itinerary (PDF or TXT) and get Google My Maps KML files — "
    "each day a colored layer with numbered pins."
)

# --- Sidebar: usage gauges + options --------------------------------------
with st.sidebar:
    st.header("API usage")
    render_usage_gauges()
    st.divider()
    st.header("Options")
    layers_per_file = st.slider(
        "Days per KML file",
        min_value=1,
        max_value=MAX_LAYERS_PER_FILE,
        value=MAX_LAYERS_PER_FILE,
        help="Google My Maps allows at most 10 layers (days) per map.",
    )
    no_geocode = st.toggle(
        "Skip geocoding (faster, less inaccurate pins)",
        value=False,
        help="Use Gemini's approximate coordinates instead of snapping each "
        "place to its exact Google Maps point.",
    )
    with st.expander("Advanced: API keys"):
        st.caption("Leave blank to use the server's configured keys.")
        gemini_key_override = st.text_input("Gemini API key", type="password")
        geo_key_override = st.text_input("Geocoding API key", type="password")

    st.divider()
    st.header("Publish to My Maps")
    st.caption(
        "Create a live Google My Maps map per file and share it — runs a browser "
        "on **this machine**, so it only works when Streamlit runs locally."
    )
    publish_enabled = st.toggle(
        "Create & share maps after generating",
        value=False,
        help="After the KML is built, drive My Maps to import each file as its own "
        "map, then share it via the Drive API.",
    )
    if publish_enabled:
        # --- Google login (Playwright persistent profile) ---
        logged_in = st.session_state.get("gmaps_logged_in")
        cols = st.columns([1, 1])
        if cols[0].button("🔐 Log in to Google", use_container_width=True):
            with st.spinner("Opening a browser window — sign in to Google, "
                            "then return here…"):
                try:
                    login()
                    st.session_state["gmaps_logged_in"] = True
                    st.success("Logged in. Session saved for future runs.")
                except Exception as e:
                    st.session_state["gmaps_logged_in"] = False
                    st.error(f"Login failed: {e}")
        if cols[1].button("Check status", use_container_width=True):
            with st.spinner("Checking the saved Google session…"):
                st.session_state["gmaps_logged_in"] = is_logged_in()
        if logged_in is True:
            st.caption("✅ Signed in to Google.")
        elif logged_in is False:
            st.caption("⚠️ Not signed in — click **Log in to Google**.")

        share_emails = st.text_input(
            "Share with (emails, comma-separated)",
            help="Each created map is shared with these people. Leave blank to "
            "create the maps without sharing.",
        )
        share_role = st.selectbox(
            "Their access", ["viewer", "commenter", "editor"], index=0,
        )
        notify_share = st.toggle("Email people when shared", value=True)
        show_browser = st.toggle(
            "Show the browser while working", value=False,
            help="Headless by default. Turn on to watch/debug the automation.",
        )
        with st.expander("Drive sharing credentials (only if sharing)"):
            st.caption(
                "Sharing uses the Google Drive API. Upload an OAuth **Desktop** "
                "client `credentials.json` (Drive API enabled). Saved locally; "
                "a browser consent runs once on first share."
            )
            cred_upload = st.file_uploader(
                "credentials.json", type=["json"], key="drive_creds"
            )
            if cred_upload is not None:
                with open(DRIVE_CREDENTIALS_FILE, "wb") as f:
                    f.write(cred_upload.getbuffer())
                st.success(f"Saved to {DRIVE_CREDENTIALS_FILE}.")
            if os.path.exists(DRIVE_CREDENTIALS_FILE):
                st.caption(f"✅ {DRIVE_CREDENTIALS_FILE} present.")
    else:
        share_emails = ""
        share_role = "viewer"
        notify_share = True
        show_browser = False

gemini_api_key = gemini_key_override or get_secret("GOOGLE_API_KEY")
geo_api_key = geo_key_override or get_secret("GEO_API_KEY")

# --- Upload ---------------------------------------------------------------
uploaded = st.file_uploader(
    "Drag & drop your itinerary here",
    type=["pdf", "txt"],
    accept_multiple_files=False,
    help="One PDF or TXT file at a time, up to %d MB." % MAX_UPLOAD_MB,
)

generate = st.button("Generate map files", type="primary", disabled=uploaded is None)


def build_zip(files: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)
    return buf.getvalue()


if generate and uploaded is not None:
    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File is too large ({uploaded.size / 1e6:.1f} MB). Max is {MAX_UPLOAD_MB} MB.")
        st.stop()
    if not gemini_api_key:
        st.error(
            "No Gemini API key configured. Set GOOGLE_API_KEY in the app secrets, "
            "or enter one under Advanced in the sidebar."
        )
        st.stop()
    if not no_geocode and not geo_api_key:
        st.warning(
            "No Geocoding API key configured — falling back to Gemini's rough "
            "coordinates. Enable 'Skip geocoding' to silence this, or set GEO_API_KEY."
        )

    ext = os.path.splitext(uploaded.name)[1].lower()
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "itinerary" + ext)
        with open(in_path, "wb") as f:
            f.write(uploaded.getbuffer())

        out_dir = os.path.join(tmp, "output")
        try:
            with st.status("Working…", expanded=True) as status:
                bar = st.progress(0.0)

                def progress(step: str, frac: float) -> None:
                    status.update(label=step)
                    bar.progress(min(max(frac, 0.0), 1.0))

                result = run_pipeline(
                    in_path,
                    gemini_api_key=gemini_api_key,
                    geo_api_key=geo_api_key,
                    output_dir=out_dir,
                    layers_per_file=layers_per_file,
                    no_geocode=no_geocode,
                    progress=progress,
                )
                status.update(label="Done", state="complete")

            # Read KML bytes into session_state so downloads survive reruns.
            st.session_state["result_meta"] = {
                "trip_name": result.trip_name,
                "days": result.days,
                "locations": result.locations,
                "corrected": result.corrected,
                "fallback": result.fallback,
            }
            st.session_state["result_files"] = [
                (os.path.basename(p), open(p, "rb").read()) for p in result.files
            ]

            # --- Optional: publish each KML to My Maps + share (local only) ---
            st.session_state.pop("map_results", None)
            if publish_enabled:
                recipients = [e.strip() for e in share_emails.split(",") if e.strip()]
                try:
                    with st.status("Publishing to Google My Maps…", expanded=True) as pstatus:
                        pbar = st.progress(0.0)

                        def publish_progress(step: str, frac: float) -> None:
                            pstatus.update(label=step)
                            pbar.progress(min(max(frac, 0.0), 1.0))

                        maps = publish_kml_files(
                            result.files,
                            trip_name=result.trip_name,
                            recipients=recipients,
                            role=share_role,
                            headless=not show_browser,
                            notify=notify_share,
                            progress=publish_progress,
                        )
                        pstatus.update(label="Published to My Maps", state="complete")
                    # Key map results by filename so the download list can link them.
                    st.session_state["map_results"] = {
                        os.path.basename(m.file): {
                            "url": m.url, "mid": m.mid,
                            "shared_with": m.shared_with, "error": m.error,
                        }
                        for m in maps
                    }
                    # Log this publish to the analytics Sheet (best-effort).
                    from gmap_planner.analytics import record_publish
                    record_publish(result.trip_name, maps)
                except Exception as e:  # auth/setup failure before per-file loop
                    st.warning(
                        "Maps couldn't be published (the KML files were still "
                        f"created): {e}"
                    )
        except PipelineError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:  # unexpected — show friendly + details
            st.error("Something went wrong while generating the map files.")
            with st.expander("Technical details"):
                st.exception(e)
            st.stop()


# --- Results (persisted across reruns) ------------------------------------
if "result_files" in st.session_state:
    meta = st.session_state["result_meta"]
    files = st.session_state["result_files"]

    st.success(f"Created {len(files)} KML file(s) for **{meta['trip_name']}**.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Days", meta["days"])
    c2.metric("Locations", meta["locations"])
    c3.metric("Exact coords", f"{meta['corrected']}/{meta['corrected'] + meta['fallback']}")

    st.subheader("Download")
    if len(files) > 1:
        st.download_button(
            f"⬇️  Download all {len(files)} files (.zip)",
            data=build_zip(files),
            file_name=f"{meta['trip_name']}.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )
        st.caption("…or grab individual day-layers:")

    map_results = st.session_state.get("map_results", {})
    if map_results:
        ok = sum(1 for m in map_results.values() if not m["error"])
        st.info(f"🌍 Published {ok}/{len(map_results)} map(s) to Google My Maps.")

    for i, (name, data) in enumerate(files, start=1):
        label = os.path.splitext(name)[0]
        day_label = f"Days {label}" if "-" in label else f"Day {label}"
        size_kb = len(data) / 1024
        mr = map_results.get(name)
        with st.container(border=True):
            if mr and not mr["error"]:
                info, btn, link = st.columns([3, 1, 1], vertical_alignment="center")
            else:
                info, btn = st.columns([3, 1], vertical_alignment="center")
                link = None
            info.markdown(f"🗺️ **{day_label}**  \n`{name}` · {size_kb:.0f} KB")
            btn.download_button(
                "⬇️ Download",
                data=data,
                file_name=name,
                mime="application/vnd.google-earth.kml+xml",
                key=f"dl_{name}",
                use_container_width=True,
            )
            if link is not None:
                view_url = (
                    f"https://www.google.com/maps/d/viewer?mid={mr['mid']}"
                    if mr.get("mid") else mr["url"]
                )
                link.link_button("🌍 Open map", view_url, use_container_width=True)
            if mr and mr["error"]:
                info.caption(f"⚠️ Map not created: {mr['error']}")
            elif mr and mr["shared_with"]:
                info.caption(f"Shared with: {', '.join(mr['shared_with'])}")

    if not map_results:
        with st.expander("How to import into Google My Maps"):
            st.markdown(
                "1. Open [Google My Maps](https://www.google.com/mymaps) → **Create a new map**.\n"
                "2. Click **Import** under a layer and upload one KML file.\n"
                "3. Each KML adds up to 10 day-layers. For longer trips, import each "
                "file into its own layer/map.\n\n"
                "_Or enable **Publish to My Maps** in the sidebar (local runs) to do "
                "this automatically and get a shareable link per file._"
            )
