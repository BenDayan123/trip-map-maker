# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the script

```bash
pip install -r requirements.txt
python main.py <itinerary.pdf|itinerary.txt> [--output-dir ./output] [--layers-per-file N]
```

Keys read from `.env` via `python-dotenv`: `GOOGLE_API_KEY=` (Gemini, `--api-key` override), `GEO_API_KEY=` (Geocoding, `--geo-api-key` override).

KML files are written to a per-trip subfolder: `<output-dir>/<trip_name>/` (trip name sanitized for the filesystem).

## Architecture

`main.py` is a thin entrypoint that calls `gmap_planner.pipeline.main`. All logic lives in the **`gmap_planner/`** package:

- **`config.py`** — constants: `GEMINI_MODEL`, `MAX_LAYERS_PER_FILE`, `GEOCODE_URL`.
- **`prompt.py`** — `GEMINI_EXTRACTION_PROMPT`: JSON schema + extraction rules (every location, Hebrew notes, `lat`/`lng` from world knowledge, `DD/MM` dates).
- **`cli.py`** — `parse_args`, `resolve_api_key`.
- **`gemini.py`** — `load_file_for_gemini` (TXT inline; PDF via `client.files.upload()`, no local parsing) + `extract_itinerary` (calls Gemini with `response_mime_type="application/json"` → `{trip_name, days: [{day, date, locations: [{name, lat, lng, notes}]}]}`; Gemini coords are rough, off 50–300m).
- **`geocode.py`** — `geocode_place` / `geocode_itinerary`: snap each name to exact coords via **Geocoding API** (`maps/api/geocode/json?address=`). Falls back to Gemini coords on failure. Skipped with `--no-geocode`.
- **`kml.py`** — `sanitize_folder_name` (trip name → safe folder), `chunk_days` (chunks of ≤ `layers_per_file`, capped at `MAX_LAYERS_PER_FILE = 10`), `numbered_pin_href` (Google `vt/icon` 3-layer stack → solid teardrop pin tinted with the day's color, stop number drawn in solid white, any count), `build_kml_file` (one `<Document>`, each day a `<Folder>`, numbered pin icons, `lng,lat,0`), `write_kml_files` (`{first}.kml` or `{first}-{last}.kml`).
- **`pipeline.py`** — `main` + `print_summary`: wires the stages, writes each trip's KML into `<output-dir>/<trip_name>/`.

Current model: `gemini-3.1-flash-lite` (set via `GEMINI_MODEL` in `config.py`).

## Key design decisions

- **KML over GeoJSON**: Google My Maps reliably imports KML (its native format); GeoJSON import is unreliable.
- **Gemini for discovery, Geocoding API for coordinates**: Gemini extracts which places appear (names + Hebrew notes); the Geocoding API resolves each name to coordinates. Personal-trip volumes stay inside the free tier (≈$0).
- **Numbered pin icons**: locations within a day are numbered sequentially so import order is visible on the map. Icons are generated on the fly by Google's My Maps icon endpoint (`mt.google.com/vt/icon`, 3-layer `pin-container,container,blank-shape` stack with `&text=N`), so numbering is **not** capped at 10 like the old `paddle/{1-10}.png` files were. The number is always solid white for contrast.
- **Per-day color**: each day's pins are tinted a distinct color keyed to the day number, cycling through `DAY_COLORS` in `config.py` (`color = DAY_COLORS[(day-1) % len]`), so days are visually separable on the map.
- **Hebrew notes**: the prompt instructs Gemini to write `notes` in Hebrew.
- **Per-trip output folder**: each run writes its KML files into `<output-dir>/<trip_name>/`, keeping multiple trips separated on disk.
- **No automated My Maps upload**: Google removed KML→My Maps conversion from the Drive API (v2 and v3) and offers no My Maps create API, so maps must be imported manually in the My Maps UI from the generated KML.
- **No local PDF pre-parsing (markitdown etc.)**: PDFs go straight to Gemini's Files API. Gemini reads native PDF text free of token charge, OCRs scanned pages, and handles Hebrew/RTL — all of which a pdfminer-based markdown step would charge for, weaken, or risk corrupting. Revisit only to support non-PDF Office formats (.docx/.xlsx), where markitdown would feed the inline-text path while PDFs stay on Gemini native.
