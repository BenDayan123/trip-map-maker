# Trip Map Maker

Turn a travel itinerary (PDF/TXT) into Google My Maps **KML** files — each day a
colored layer with numbered pins. Gemini extracts the places; the Geocoding API
snaps them to exact coordinates.

## Two ways to use it

### Web GUI (Streamlit)
Drag-and-drop upload, live progress, and download buttons.

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

API keys are read from `st.secrets` then environment variables:
- Local: copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml` and fill in
  `GOOGLE_API_KEY` (Gemini) and `GEO_API_KEY` (Geocoding). This file is gitignored.

### CLI
```bash
python main.py <itinerary.pdf|itinerary.txt> [--output-dir ./output] [--layers-per-file N] [--no-geocode]
```
Keys via `.env` (`GOOGLE_API_KEY=`, `GEO_API_KEY=`) or `--api-key` / `--geo-api-key`.

## Deploy the web app

**Streamlit Community Cloud (zero-cost, easiest):** push this repo to GitHub →
[share.streamlit.io](https://share.streamlit.io) → new app → entrypoint
`streamlit_app.py` → set `GOOGLE_API_KEY` and `GEO_API_KEY` in the app's Secrets.
Admins just open the URL — nothing to install.

**Docker (Render / Fly.io / a VPS):**
```bash
docker build -t trip-map-maker .
docker run -p 8501:8501 -e GOOGLE_API_KEY=... -e GEO_API_KEY=... trip-map-maker
```

## Importing into Google My Maps
Automatic upload isn't possible (Google removed the My Maps import API), so import
each KML manually: [My Maps](https://www.google.com/mymaps) → Create a new map →
Import → upload a KML. Each file holds up to 10 day-layers.

## Architecture

`gmap_planner/` package, CLI and GUI share one entry point:
- `service.run_pipeline(...)` — runs all stages, reports progress via a callback,
  returns a `PipelineResult`, raises `PipelineError` on failure (never exits).
- `pipeline.main` — thin CLI wrapper; `streamlit_app.py` — the GUI; both call `run_pipeline`.
- Stages: `gemini` (extract) · `geocode` (snap coords) · `kml` (build/write).

## Roadmap: shared sales analytics (not built yet)
Planned: record each sale (`trip_name`, file count, price, buyer, admin, timestamp)
to a shared cloud database (e.g. Supabase Postgres), an `Analytics` dashboard page
under a `pages/` dir, and a simple shared login. `run_pipeline` already returns a
`PipelineResult` that such a logger can consume.
