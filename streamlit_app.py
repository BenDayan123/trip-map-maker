"""Streamlit GUI for the itinerary → Google My Maps KML planner.

Run locally:   streamlit run streamlit_app.py
Hosted:        deploy to Streamlit Community Cloud (or any host) and set the
               GOOGLE_API_KEY / GEO_API_KEY secrets.

API keys are read from st.secrets first, then environment variables, so the same
code works hosted and locally. Admins normally never see or enter keys.
"""

import io
import os
import tempfile
import zipfile

import streamlit as st

from gmap_planner.config import MAX_LAYERS_PER_FILE
from gmap_planner.errors import PipelineError
from gmap_planner.service import run_pipeline

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


# --- Header ---------------------------------------------------------------
st.title("🗺️ Trip Map Maker")
st.caption(
    "Upload a travel itinerary (PDF or TXT) and get Google My Maps KML files — "
    "each day a colored layer with numbered pins."
)

# --- Sidebar options ------------------------------------------------------
with st.sidebar:
    st.header("Options")
    layers_per_file = st.slider(
        "Days per KML file",
        min_value=1,
        max_value=MAX_LAYERS_PER_FILE,
        value=MAX_LAYERS_PER_FILE,
        help="Google My Maps allows at most 10 layers (days) per map.",
    )
    no_geocode = st.toggle(
        "Skip geocoding (faster, rougher pins)",
        value=False,
        help="Use Gemini's approximate coordinates instead of snapping each "
        "place to its exact Google Maps point.",
    )
    with st.expander("Advanced: API keys"):
        st.caption("Leave blank to use the server's configured keys.")
        gemini_key_override = st.text_input("Gemini API key", type="password")
        geo_key_override = st.text_input("Geocoding API key", type="password")

gemini_api_key = gemini_key_override or get_secret("GOOGLE_API_KEY")
geo_api_key = geo_key_override or get_secret("GEO_API_KEY")

# --- Upload ---------------------------------------------------------------
uploaded = st.file_uploader(
    "Drag & drop your itinerary here",
    type=["pdf", "txt"],
    help="PDF or TXT, up to %d MB." % MAX_UPLOAD_MB,
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
            "⬇️ Download all (.zip)",
            data=build_zip(files),
            file_name=f"{meta['trip_name']}.zip",
            mime="application/zip",
            type="primary",
        )
    for name, data in files:
        st.download_button(
            f"⬇️ {name}",
            data=data,
            file_name=name,
            mime="application/vnd.google-earth.kml+xml",
            key=f"dl_{name}",
        )

    with st.expander("How to import into Google My Maps"):
        st.markdown(
            "1. Open [Google My Maps](https://www.google.com/mymaps) → **Create a new map**.\n"
            "2. Click **Import** under a layer and upload one KML file.\n"
            "3. Each KML adds up to 10 day-layers. For longer trips, import each "
            "file into its own layer/map.\n\n"
            "_Automatic upload isn't possible — Google removed the My Maps import "
            "API, so this step is manual._"
        )
