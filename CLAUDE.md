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
- **`prompt.py`** — `GEMINI_EXTRACTION_PROMPT`: JSON schema + extraction rules (every location, Hebrew notes, `lat`/`lng` from world knowledge, `DD/MM` dates). Written for the real input: a Hebrew/RTL document whose place names are Hebrew, English or the local language, mixed mid-sentence. It enumerates the place types to collect (shops, streets, markets, nature reserves, temples, malls, viewpoints, hotels, airports, …), demands places hidden in tables/parentheses/footnotes/alternatives, splits compound mentions, and fixes `name` to the form the Geocoding API resolves (`"Nishiki Market, Kyoto"`), translating a Hebrew-written foreign name to the name Google Maps knows. Measured on `tests/plan.pdf` 92 → 115 places and `tests/plan2.pdf` 60 → 155 versus the previous prompt.
- **`cli.py`** — `parse_args`, `resolve_api_key`.
- **`gemini.py`** — `load_file_for_gemini` (TXT inline; PDF via `client.files.upload()`, no local parsing) + `extract_itinerary` (calls Gemini with `response_mime_type="application/json"` → `{trip_name, days: [{day, date, locations: [{name, lat, lng, notes}]}]}`; Gemini coords are rough, off 50–300m). Guards against the intermittent "invalid JSON": a `response_schema` plus one retry of the whole call (`ATTEMPTS`) when the *body* is unusable — truncated, empty, or missing `trip_name`/`days` (`_BadResponse`). A failed **request** (bad key, quota, network) is not retried: it fails the same way twice and re-uploads the whole itinerary. `max_output_tokens` is deliberately left unset — unset means the model's own maximum (65536 for `gemini-3.1-flash-lite`), so any value set here could only lower the ceiling. Error messages carry the `finish_reason`, never the raw body. `gmap_planner/test_gemini_extract.py` covers both retry and no-retry paths with a fake client.
- **`geocode.py`** — `geocode_place` / `geocode_itinerary`: snap each name to exact coords via **Geocoding API** (`maps/api/geocode/json?address=`). Falls back to Gemini coords on failure. Skipped with `--no-geocode`.
- **`kml.py`** — `sanitize_folder_name` (trip name → safe folder), `chunk_days` (chunks of ≤ `layers_per_file`, capped at `MAX_LAYERS_PER_FILE = 10`), `numbered_pin_href` (Google `vt/icon` 3-layer stack → solid teardrop pin tinted with the day's color, stop number drawn in solid white, any count), `build_kml_file` (one `<Document>`, each day a `<Folder>`, numbered pin icons, `lng,lat,0`), `write_kml_files` (`{first}.kml` or `{first}-{last}.kml`).
- **`pipeline.py`** — `main` + `print_summary`: wires the stages, writes each trip's KML into `<output-dir>/<trip_name>/`. When `--share` is given, calls `publish._publish` afterwards; `--login` short-circuits to `mymaps.login`.
- **`mymaps.py`** — Playwright automation of the My Maps editor (no API exists): `MyMapsSession` (`create_map_from_kml` creates a map, imports the KML via the file input on any frame, sets the title, returns `{url, mid}`) + `login` (one-time headed sign-in). Two auth modes: **local** uses a persistent Chromium profile (`_launch_persistent`); **seeded** (`storage_state=`) launches a headless throwaway context restored from a captured session (`_launch_with_storage_state`) — the only way to run signed-in on a headless host. `ensure_chromium()` fetches the browser binary at runtime (for Cloud, where `playwright install` never runs, and for a packaged app whose build didn't bundle one — frozen, it runs Playwright's own node driver CLI since there's no `python -m playwright`); `_browsers_path()` sets `PLAYWRIGHT_BROWSERS_PATH` when frozen to `"0"` (the browser bundled inside the playwright package by `build_app.sh`) or else to a writable per-user dir; `export_session` does a headed login then dumps `storage_state.json` for the `GOOGLE_STORAGE_STATE` secret (`python main.py --export-session`). Selectors are centralized (`SEL_*`) and `hl=en` is forced; failures dump a `*.error.png` next to the KML. Flakiness guards: `_do_import` retries click→set-file→dialog-closes up to 3× and Escapes a Picker left open by a failed upload (anything clicked behind that modal is swallowed); Google's "Your action was reverted" toast (`SEL_REVERTED`) aborts the waits immediately and triggers `_recover_from_revert` (settle + reload the editor, only once `mid` exists) instead of sitting out a 25s/40s timeout, with `MAP_GAP_S` spacing consecutive maps because back-to-back creation is what provokes the revert; and the rename clicks the map's **current** name read from the tab title (`map_name_from_tab`) rather than the literal "Untitled map" — importing a KML makes My Maps rename the map after the file, so that text is often already gone. `gmap_planner/test_mymaps_helpers.py` covers both without a browser (`/tests` is gitignored, so the check lives in the package).
- **`drive_share.py`** — Drive API sharing: `get_drive_service` (OAuth installed-app flow, full `drive` scope, `token.json` cache) + `share_map` (grants `permissions.create` to each email; `mid` → Drive file id, with a title search fallback). `normalize_role` maps viewer/editor/… → reader/writer/commenter. `restrict_download` sets `copyRequiresWriterPermission=True` — the API form of the Share → gear → "Commenters and viewers" checkbox under *download, print, and copy* — so no dialog has to be driven; best-effort, a failure only warns.
- **`publish.py`** — orchestrator: `publish_kml_files` opens one `MyMapsSession`, creates + shares one map per KML file, returns a `PublishedMap` per file (per-file errors captured, never aborts the batch). Every created map also gets `restrict_download`, so Drive auth is attempted even with no recipients — but stays optional there (missing `credentials.json` only fails the run when there *are* recipients).
- **`analytics.py`** — appends each publish to a Google Sheet (`record_publish` → one row: `Created At, Trip Name, Maps, Places, Map Links`, written `USER_ENTERED` so the timestamp is a real date; `Places` is the pin count summed over the run's KML files via `places_in_kml`; `fetch_rows` reads the table columns back and normalizes headers to canonical keys — `Created At` → `created_at` — so an un-migrated sheet still works). `ensure_layout` makes the Sheet readable in the browser: display header, frozen/bold header row, banding, column widths, basic filter, and a **live formula summary box** to the right of the table (totals + maps/places this calendar month). Layout positions are derived from `COLUMNS`, so adding a column shifts the gutter, summary and formulas automatically. It's idempotent (one read when already tidy), re-shapes a sheet on any older column set after duplicating it to a `Backup (pre-format)` tab, and `_worksheet` picks the first tab that *isn't* that backup. The tidy check compares the whole summary label column, not just its title: the box shares rows with the table, so deleting a log row in the browser eats a label — the next call restores it. Auth reuses the `GCP_SA_JSON` service account via `gspread`; target Sheet is `ANALYTICS_SHEET_ID`. Best-effort — any Sheets failure logs a warning and returns, never breaking map generation. Read by the **`pages/Analytics.py`** page (open, no password gate; has a "Tidy up the Sheet" button).

Current model: `gemini-3.1-flash-lite` (set via `GEMINI_MODEL` in `config.py`).

## Deployment (single admin, local Windows)

The app is run by a couple of admins on their own PC (Windows or macOS) — **not** hosted
for other users.
This is deliberate: locally, Playwright drives real Chrome/Edge and `credentials.json`,
`token.json`, `.pw-profile/`, and the API keys all persist on disk (set once), so the
whole class of cloud problems (ephemeral disk, headless Google login) doesn't apply.

**Shipped as a standalone Windows app**, so the admin needs no Python/terminal:
`build_exe.bat` freezes it with `streamlit-desktop-app` (PyInstaller + pywebview) into
`dist/TripMapMaker/`, and `build_installer.bat` wraps that into a per-user
`TripMapMaker-Setup.exe` via `installer.iss` (Inno Setup 6). Frozen-app specifics:
`gmap_planner/paths.py` `data_dir()` returns `%APPDATA%\TripMapMaker` when
`sys.frozen` (the exe's cwd is a temp unpack dir); `config.py` anchors the profile/token/
credentials there; keys are entered in the sidebar **🔑 Settings** page and saved to
`data_dir/config.json` (there's no `secrets.toml` in a packaged exe — `get_secret` falls
back to it); the frozen app prefers an installed Chrome/Edge channel but no longer
depends on one (see the macOS notes below).
A sidebar **⚙️ Setup status** expander (`render_setup_status`) shows what's configured.
`SETUP.md` is the admin guide. The Streamlit-Cloud publish path (`packages.txt`,
`GOOGLE_STORAGE_STATE`) remains in the repo but is unused in this local flow.

**Also shipped as a macOS app** (`build_app.sh` → `My Maps Generator.app`, `build_dmg.sh`
→ `.dmg`, both built in `.github/workflows/build-macos.yml`; `merge_universal.sh` lipos the
arm64 + x86_64 builds into a universal one). What differs from Windows, all of it
mac-only breakage that was fixed rather than theory:
- **Browser**: a `.app` has no `~/Library/Caches/ms-playwright` and no `python -m
  playwright` to fill one, so publishing worked only where Chrome happened to be
  installed. `build_app.sh` runs `PLAYWRIGHT_BROWSERS_PATH=0 playwright install chromium`
  *before* PyInstaller so `--collect-all playwright` bundles the browser (~150MB), then
  restores the exec bits PyInstaller drops on the node driver + browser binaries.
  `check_bundled_chromium` then **launches** that browser headless and fails the build if
  it doesn't run — a directory-exists check would pass for a browser PyInstaller mangled,
  left non-executable, or left with an invalid nested signature (which Apple Silicon
  kills on sight). It also asserts the browser sits exactly where `_browsers_path()`
  looks. `ensure_chromium()` downloads as a runtime fallback. The **Windows** installer
  bundles no browser on purpose (Edge ships with Windows), so `ensure_chromium()` returns
  early when frozen there instead of downloading 150MB it would never use.
- **Shutdown**: pywebview's Cocoa runtime and multiprocessing's spawn machinery leave
  non-daemon threads alive, so returning from `desktop.start()` hung the process with the
  window already gone ("can't quit the app"). It reaps the Streamlit child and then
  `os._exit(0)` on every path (`1` + a traceback in `data_dir/last_error.log` when the
  start failed — a windowed `.app` has nowhere to print, so without it a failed launch
  just vanishes). `desktop.py --selfcheck` runs the start→stop cycle and is executed
  against the built `.app` in CI, but it does **not** open a window, so a pywebview/Cocoa
  regression still needs a real Mac.
- **Codesign**: `codesign --verify --deep --strict` trips on the nested Chromium.app after
  PyInstaller's copy — the top-level verify is the gate, the deep one only warns. The
  thing that actually catches a broken nested signature is the Chromium launch above.
- **pywebview**: `--collect-all webview` is required (its `webview/js/*.js` are runtime
  data files).
- **Updater**: a release ships both an Intel and a universal `.dmg`, so
  `updater._platform_asset` picks by CPU instead of taking the first `.dmg`.
- **Universal merge**: `merge_universal.sh` now also lipos two full Chromium trees, and
  its per-file fallback is "keep the arm64 copy" — which would hand an Intel user a
  browser that can't start. It asserts the bundled Chromium came out fat and prints the
  merged app's size (the `.dmg` is what the updater downloads).

## Key design decisions

- **KML over GeoJSON**: Google My Maps reliably imports KML (its native format); GeoJSON import is unreliable.
- **Gemini for discovery, Geocoding API for coordinates**: Gemini extracts which places appear (names + Hebrew notes); the Geocoding API resolves each name to coordinates. Personal-trip volumes stay inside the free tier (≈$0).
- **Numbered pin icons**: locations within a day are numbered sequentially so import order is visible on the map. Icons are generated on the fly by Google's My Maps icon endpoint (`mt.google.com/vt/icon`, 3-layer `pin-container,container,blank-shape` stack with `&text=N`), so numbering is **not** capped at 10 like the old `paddle/{1-10}.png` files were. The number is always solid white for contrast.
- **Per-day color**: each day's pins are tinted a distinct color keyed to the day number, cycling through `DAY_COLORS` in `config.py` (`color = DAY_COLORS[(day-1) % len]`), so days are visually separable on the map.
- **Hebrew notes**: the prompt instructs Gemini to write `notes` in Hebrew.
- **Per-trip output folder**: each run writes its KML files into `<output-dir>/<trip_name>/`, keeping multiple trips separated on disk.
- **My Maps automation via browser, sharing via Drive API**: Google offers no My Maps create/import API, so map creation + KML import are done by driving the My Maps editor with Playwright (`mymaps.py`). Sharing, however, *does* have an API — a My Maps map is a Drive file (`application/vnd.google-apps.map`), so `drive_share.py` grants access with `permissions.create` rather than driving the brittle share dialog. The browser step is opt-in (`--share`), uses a persistent profile so the Google login is reused (one-time `--login`). It's available in both the CLI and the Streamlit app, but **only when Streamlit runs locally** — a hosted deployment has no browser, so the "Publish to My Maps" sidebar section (login button, recipients, role, per-file map links) drives a local Chrome. The UI selectors are inherently fragile to Google UI changes — expect occasional tuning of the `SEL_*` constants. `mymaps.is_logged_in` powers the UI's login-status check.
- **Publishing from a hosted (headless) deploy**: publishing normally needs a local browser + an interactive Google login, so it's local-only by default. To run it on Streamlit Community Cloud, two things are provided: `packages.txt` lists chromium's apt libs (Cloud has no terminal), and `ensure_chromium()` fetches the browser binary at runtime; the interactive login is replaced by a **captured `storage_state`** (secret `GOOGLE_STORAGE_STATE`, produced locally by `--export-session`) that `MyMapsSession(storage_state=...)` restores headless. **Caveat**: Google often re-challenges a session replayed from a datacenter IP, so Cloud publishing may still fail at Google's gate — fallbacks are a public-KML `maps?q=<url>` link or a self-hosted worker.
- **Analytics via a Google Sheet, not a DB**: publishes are logged to a hosted Google Sheet (`analytics.py`) rather than a local SQLite file, because map creation only runs locally (needs a browser) while the admin views analytics on the hosted Streamlit app — Streamlit Community Cloud's disk is ephemeral, so a local SQLite file wouldn't persist or be reachable. The Sheet is hosted by Google (survives redeploys), readable from anywhere, and the admin can eyeball/edit rows in the browser with no SQL. Streamlit's native multipage layout (`pages/Analytics.py`) adds the sidebar nav; the page is open to read (no password gate). New columns are added by extending `COLUMNS` (canonical key → display title) + the row in `analytics.py` (older, shorter rows are tolerated). Because the Sheet is a *read surface* for the admin, the code owns its presentation too — `ensure_layout` writes the styling and a formula-based summary box, so the numbers stay live in Sheets without the app being open, and the Streamlit table mirrors the same column titles. Secrets: `GCP_SA_JSON` (reused from the usage gauges — grant it Editor on the Sheet, enable the Sheets API), `ANALYTICS_SHEET_ID`.
- **No local PDF pre-parsing (markitdown etc.)**: PDFs go straight to Gemini's Files API. Gemini reads native PDF text free of token charge, OCRs scanned pages, and handles Hebrew/RTL — all of which a pdfminer-based markdown step would charge for, weaken, or risk corrupting. Revisit only to support non-PDF Office formats (.docx/.xlsx), where markitdown would feed the inline-text path while PDFs stay on Gemini native.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
