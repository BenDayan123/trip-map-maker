# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the script

```bash
pip install -r requirements.txt
python main.py <itinerary.pdf|itinerary.txt> [--output-dir ./output] [--layers-per-file N]
```

Keys read from `.env` via `python-dotenv`: `GOOGLE_API_KEY=` (Gemini, `--api-key` override), `GEO_API_KEY=` (Geocoding, `--geo-api-key` override).

KML files are written to a per-trip subfolder: `<output-dir>/<trip_name>/` (trip name sanitized for the filesystem).

### Autonomous My Maps publish + share (optional)

```bash
playwright install chromium          # one-time, after pip install
python main.py --login               # one-time headed Google login (saved to .pw-profile/)
python main.py trip.pdf --share alice@x.com,bob@y.com [--share-role editor] [--headed] [--no-notify]
```

With `--share`, after the KML files are written the pipeline drives the My Maps
editor with Playwright to create **one map per KML file**, imports the KML, names
the map, then shares it via the **Drive API** with the listed people, printing each
live map URL. Needs a `credentials.json` OAuth Desktop client (Drive API enabled);
a `token.json` is cached after first consent. Both are gitignored, as is `.pw-profile/`.

## Architecture

`main.py` is a thin entrypoint that calls `gmap_planner.pipeline.main`. All logic lives in the **`gmap_planner/`** package:

- **`config.py`** — constants: `GEMINI_MODEL`, `MAX_LAYERS_PER_FILE`, `GEOCODE_URL`.
- **`prompt.py`** — `GEMINI_EXTRACTION_PROMPT`: JSON schema + extraction rules (every location, Hebrew notes, `lat`/`lng` from world knowledge, `DD/MM` dates).
- **`cli.py`** — `parse_args`, `resolve_api_key`.
- **`gemini.py`** — `load_file_for_gemini` (TXT inline; PDF via `client.files.upload()`, no local parsing) + `extract_itinerary` (calls Gemini with `response_mime_type="application/json"` → `{trip_name, days: [{day, date, locations: [{name, lat, lng, notes}]}]}`; Gemini coords are rough, off 50–300m).
- **`geocode.py`** — `geocode_place` / `geocode_itinerary`: snap each name to exact coords via **Geocoding API** (`maps/api/geocode/json?address=`). Falls back to Gemini coords on failure. Skipped with `--no-geocode`.
- **`kml.py`** — `sanitize_folder_name` (trip name → safe folder), `chunk_days` (chunks of ≤ `layers_per_file`, capped at `MAX_LAYERS_PER_FILE = 10`), `numbered_pin_href` (Google `vt/icon` 3-layer stack → solid teardrop pin tinted with the day's color, stop number drawn in solid white, any count), `build_kml_file` (one `<Document>`, each day a `<Folder>`, numbered pin icons, `lng,lat,0`), `write_kml_files` (`{first}.kml` or `{first}-{last}.kml`).
- **`pipeline.py`** — `main` + `print_summary`: wires the stages, writes each trip's KML into `<output-dir>/<trip_name>/`. When `--share` is given, calls `publish._publish` afterwards; `--login` short-circuits to `mymaps.login`.
- **`mymaps.py`** — Playwright automation of the My Maps editor (no API exists): `MyMapsSession` (`create_map_from_kml` creates a map, imports the KML via the file input on any frame, sets the title, returns `{url, mid}`) + `login` (one-time headed sign-in). Two auth modes: **local** uses a persistent Chromium profile (`_launch_persistent`); **seeded** (`storage_state=`) launches a headless throwaway context restored from a captured session (`_launch_with_storage_state`) — the only way to run signed-in on a headless host. `ensure_chromium()` fetches the browser binary at runtime (for Cloud, where `playwright install` never runs); `export_session` does a headed login then dumps `storage_state.json` for the `GOOGLE_STORAGE_STATE` secret (`python main.py --export-session`). Selectors are centralized (`SEL_*`) and `hl=en` is forced; failures dump a `*.error.png` next to the KML.
- **`drive_share.py`** — Drive API sharing: `get_drive_service` (OAuth installed-app flow, full `drive` scope, `token.json` cache) + `share_map` (grants `permissions.create` to each email; `mid` → Drive file id, with a title search fallback). `normalize_role` maps viewer/editor/… → reader/writer/commenter.
- **`publish.py`** — orchestrator: `publish_kml_files` opens one `MyMapsSession`, creates + shares one map per KML file, returns a `PublishedMap` per file (per-file errors captured, never aborts the batch).
- **`analytics.py`** — appends each publish to a Google Sheet (`record_publish` → one row: `created_at, trip_name, map_links`; `fetch_rows` reads them back). Auth reuses the `GCP_SA_JSON` service account via `gspread`; target Sheet is `ANALYTICS_SHEET_ID`. Best-effort — any Sheets failure logs a warning and returns, never breaking map generation. Read by the admin-only **`pages/Analytics.py`** page (gated by `ADMIN_PASSWORD`).

Current model: `gemini-3.1-flash-lite` (set via `GEMINI_MODEL` in `config.py`).

## Deployment (single admin, local Windows)

The app is run by one admin on their own Windows PC — **not** hosted for other users.
This is deliberate: locally, Playwright drives real Chrome and `credentials.json`,
`token.json`, `.pw-profile/`, and the API keys all persist on disk (set once), so the
whole class of cloud problems (ephemeral disk, headless Google login) doesn't apply.
One-click batch launchers wrap the flow: `setup.bat` (venv + deps + `playwright install
chromium`), `login.bat` (`python main.py --login`), `run.bat` (auto `git pull --ff-only`
then `streamlit run`; `run.vbs` runs it with no console), `update.bat` (`git pull` + pip).
`SETUP.md` is the admin guide. A sidebar **⚙️ Setup status** expander
(`render_setup_status` in `streamlit_app.py`) shows which one-time items are configured.
The Streamlit-Cloud publish path (`packages.txt`, `GOOGLE_STORAGE_STATE`) remains in the
repo but is unused in this local flow.

## Key design decisions

- **KML over GeoJSON**: Google My Maps reliably imports KML (its native format); GeoJSON import is unreliable.
- **Gemini for discovery, Geocoding API for coordinates**: Gemini extracts which places appear (names + Hebrew notes); the Geocoding API resolves each name to coordinates. Personal-trip volumes stay inside the free tier (≈$0).
- **Numbered pin icons**: locations within a day are numbered sequentially so import order is visible on the map. Icons are generated on the fly by Google's My Maps icon endpoint (`mt.google.com/vt/icon`, 3-layer `pin-container,container,blank-shape` stack with `&text=N`), so numbering is **not** capped at 10 like the old `paddle/{1-10}.png` files were. The number is always solid white for contrast.
- **Per-day color**: each day's pins are tinted a distinct color keyed to the day number, cycling through `DAY_COLORS` in `config.py` (`color = DAY_COLORS[(day-1) % len]`), so days are visually separable on the map.
- **Hebrew notes**: the prompt instructs Gemini to write `notes` in Hebrew.
- **Per-trip output folder**: each run writes its KML files into `<output-dir>/<trip_name>/`, keeping multiple trips separated on disk.
- **My Maps automation via browser, sharing via Drive API**: Google offers no My Maps create/import API, so map creation + KML import are done by driving the My Maps editor with Playwright (`mymaps.py`). Sharing, however, *does* have an API — a My Maps map is a Drive file (`application/vnd.google-apps.map`), so `drive_share.py` grants access with `permissions.create` rather than driving the brittle share dialog. The browser step is opt-in (`--share`), uses a persistent profile so the Google login is reused (one-time `--login`). It's available in both the CLI and the Streamlit app, but **only when Streamlit runs locally** — a hosted deployment has no browser, so the "Publish to My Maps" sidebar section (login button, recipients, role, per-file map links) drives a local Chrome. The UI selectors are inherently fragile to Google UI changes — expect occasional tuning of the `SEL_*` constants. `mymaps.is_logged_in` powers the UI's login-status check.
- **Publishing from a hosted (headless) deploy**: publishing normally needs a local browser + an interactive Google login, so it's local-only by default. To run it on Streamlit Community Cloud, two things are provided: `packages.txt` lists chromium's apt libs (Cloud has no terminal), and `ensure_chromium()` fetches the browser binary at runtime; the interactive login is replaced by a **captured `storage_state`** (secret `GOOGLE_STORAGE_STATE`, produced locally by `--export-session`) that `MyMapsSession(storage_state=...)` restores headless. **Caveat**: Google often re-challenges a session replayed from a datacenter IP, so Cloud publishing may still fail at Google's gate — fallbacks are a public-KML `maps?q=<url>` link or a self-hosted worker.
- **Analytics via a Google Sheet, not a DB**: publishes are logged to a hosted Google Sheet (`analytics.py`) rather than a local SQLite file, because map creation only runs locally (needs a browser) while the admin views analytics on the hosted Streamlit app — Streamlit Community Cloud's disk is ephemeral, so a local SQLite file wouldn't persist or be reachable. The Sheet is hosted by Google (survives redeploys), readable from anywhere, and the admin can eyeball/edit rows in the browser with no SQL. Streamlit's native multipage layout (`pages/Analytics.py`) adds the sidebar nav; the page is gated by an `ADMIN_PASSWORD` secret. New columns are added by extending `HEADER` + the row in `analytics.py` (older, shorter rows are tolerated). Secrets: `GCP_SA_JSON` (reused from the usage gauges — grant it Editor on the Sheet, enable the Sheets API), `ANALYTICS_SHEET_ID`, `ADMIN_PASSWORD`.
- **No local PDF pre-parsing (markitdown etc.)**: PDFs go straight to Gemini's Files API. Gemini reads native PDF text free of token charge, OCRs scanned pages, and handles Hebrew/RTL — all of which a pdfminer-based markdown step would charge for, weaken, or risk corrupting. Revisit only to support non-PDF Office formats (.docx/.xlsx), where markitdown would feed the inline-text path while PDFs stay on Gemini native.
