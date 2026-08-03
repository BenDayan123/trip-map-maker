# tasks.md - Loop Engineering Starter

## Instructions
first read and use the project's graph in @graphify-out/GRAPH_REPORT.md
The agent checks this file every 2 minutes and implements anything marked `pending`.

## Format
```
- [ ] task id | description | status: pending
- [ ] task id | description | status: done
```

---

## Tasks
---

## Completed
- task-01 | macOS app freeze on close | status: done — `desktop.py` reaps the Streamlit child then `os._exit(0)` on every exit path (pywebview's Cocoa runtime + multiprocessing spawn left non-daemon threads that hung interpreter shutdown); server wait raised to 60s for a cold frozen launch. `5d40a3d`
- task-02 | Gemini returns invalid JSON | status: done — one retry of the call when the response body is unusable (truncated / empty / missing `trip_name`+`days`); a failed request (quota, auth, network) is not retried. `max_output_tokens` left unset: the model's default already is its maximum (65536), so setting one could only lower it. Also dropped a line in the prompt that demanded a JSON *array* while the schema required an object. Self-check: `gmap_planner/test_gemini_extract.py`. `8ea63c0`
- task-03 | Gemini misses places in the itinerary | status: done — prompt rewritten for Hebrew/RTL multi-script documents, with the full tourist place-type list, places hidden in tables/parentheses/alternatives, and Google-Maps-resolvable `name`s. Measured: `tests/plan.pdf` 92 → 115 places, `tests/plan2.pdf` 60 → 155; day-2 spot check showed all 16 quoted from the PDF (old prompt found 2). `ff9862f`
- task-04 | macOS (Apple Silicon) bugs | status: done — `--collect-all webview` (pywebview's JS assets), updater picks the universal `.dmg` on Apple Silicon instead of the Intel one, deep-codesign verify downgraded to a warning, stale `login.bat` / `TripMapMaker.app` references corrected, and CI now runs the frozen app's `--selfcheck` on the macOS runner plus a hard check that Chromium is bundled. `2b0760d`, `a0c84eb`
- task-05 | macOS app has no Playwright browser | status: done — `build_app.sh` installs Chromium with `PLAYWRIGHT_BROWSERS_PATH=0` so it is bundled into the `.app`, restores the exec bits PyInstaller drops, and then **launches the bundled browser headless and fails the build if it doesn't run** (catches a mangled copy, a missing exec bit, a bad nested signature); the runtime points `PLAYWRIGHT_BROWSERS_PATH` at it and `ensure_chromium()` downloads via Playwright's node driver when a build has none. No Chrome install needed. `df1aa73`, review fixes in the follow-up commit.
