#!/usr/bin/env bash
# Build the standalone macOS app bundle (dist/My Maps Generator.app).
#
# Mac counterpart of build_exe.bat. PyInstaller is NOT a cross-compiler, so this
# must run ON a Mac (Apple Silicon or Intel) with Python 3.11+ installed. The
# resulting .app matches the arch of the machine that builds it.
#
# One-time:  pip install -r requirements.txt streamlit-desktop-app
#            (this script installs Chromium into the app bundle itself, so users
#             need no separately-installed browser — see below)
# Then:      ./build_app.sh                   # -> dist/My Maps Generator.app
#            ./build_dmg.sh                    # -> TripMapMaker.dmg (drag-to-install)
set -euo pipefail
cd "$(dirname "$0")"

if [ -d ".venv/bin" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

python -c "import PyInstaller" 2>/dev/null || python -m pip install pyinstaller

# Install Chromium *inside* the playwright package (PLAYWRIGHT_BROWSERS_PATH=0)
# so `--collect-all playwright` bundles the browser into the .app. Without this
# the browser lands in ~/Library/Caches/ms-playwright and is NOT packaged, so a
# user without Google Chrome installed has no browser to drive. The runtime sets
# the same env var (gmap_planner/mymaps.py) to find it. ~150MB, worth it: no
# dependency on the user having Chrome.
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium

# Freeze desktop.py (our launcher — bounded shutdown so the window actually
# quits) instead of the streamlit-desktop-app wrapper, whose join()-with-no-
# timeout hangs the app on close. Flags mirror what that wrapper passed:
# --collect-all/--copy-metadata streamlit + streamlit_app.py bundled as data.
pyinstaller --noconfirm --windowed --name "My Maps Generator" \
  --icon icon.icns \
  --paths . \
  --collect-all streamlit \
  --copy-metadata streamlit \
  --collect-all playwright \
  --collect-all webview \
  --collect-all google \
  --collect-all googleapiclient \
  --collect-all google_auth_oauthlib \
  --collect-all gspread \
  --add-data "streamlit_app.py:." \
  --add-data "gmap_planner:gmap_planner" \
  --add-data "pages:pages" \
  desktop.py

# Trim ~90MB of unused Google API discovery docs; keep only Drive (the only API
# this app calls via googleapiclient). Safe: build('drive','v3') reads these.
DOCS="dist/My Maps Generator.app/Contents/Resources/googleapiclient/discovery_cache/documents"
[ -d "$DOCS" ] || DOCS="dist/My Maps Generator/_internal/googleapiclient/discovery_cache/documents"
if [ -d "$DOCS" ]; then
  echo "Trimming unused Google API discovery docs..."
  find "$DOCS" -type f -name '*.json' ! -name 'drive.v2.json' ! -name 'drive.v3.json' -delete
fi

# Trim confirmed-dead google.api protobuf stubs (annotations_pb2.py etc.), force-
# bundled by --collect-all google via googleapis-common-protos. Every Google call
# in this repo is REST/JSON (genai SDK, googleapiclient discovery, gspread, raw
# urllib to Cloud Monitoring) — nothing imports google.api.*_pb2. Leaves
# google/api_core and google/protobuf untouched (not confirmed dead).
API_PROTO="dist/My Maps Generator.app/Contents/Resources/google/api"
[ -d "$API_PROTO" ] || API_PROTO="dist/My Maps Generator/_internal/google/api"
if [ -d "$API_PROTO" ]; then
  echo "Trimming unused google.api protobuf stubs..."
  find "$API_PROTO" -maxdepth 1 -type f \( -name '*_pb2.py' -o -name '*_pb2.pyi' \) -delete
  find "$API_PROTO" -type d -name '__pycache__' -exec rm -rf {} +
fi

# PyInstaller copies collected data files without their exec bit, so Playwright's
# node driver and the bundled Chromium land non-executable ("Permission denied" /
# "Executable doesn't exist" at publish time). Restore it across the driver tree
# (chmod +x on the .js/.json in there is harmless). Must run BEFORE codesign —
# changing a file afterwards invalidates the signature.
APP="dist/My Maps Generator.app"
echo "Restoring exec bits on the bundled Playwright driver/browser..."
find "$APP" -type d -name driver -path '*playwright*' -exec chmod -R a+x {} +
if [ -z "$(find "$APP" -type d -name '.local-browsers' -print -quit)" ]; then
  echo "WARNING: Chromium was not bundled into the app — it will be downloaded on"
  echo "         first publish instead (needs internet). Check the playwright"
  echo "         install step above."
fi

# Ad-hoc codesign so Gatekeeper doesn't reject the unsigned app as "damaged" on
# Apple Silicon (no paid Developer ID — users still do a one-time Open Anyway,
# see INSTALL_MACOS.md). Signing the whole bundle also covers a build made in an
# Intel VM (native arch = x86_64), which then runs on Intel + Apple Silicon (via
# Rosetta 2). Done here so both the CI workflow and a local/VM build get a signed
# app from one place.
echo "Ad-hoc codesigning $APP ..."
codesign --force --deep --sign - "$APP"
# Top-level signature is what Gatekeeper checks — that one must pass. The deep
# pass walks the nested Chromium.app too, which routinely trips --strict (its
# framework layout doesn't survive PyInstaller's copy); warn, don't fail the build.
codesign --verify --strict "$APP"
codesign --verify --deep --strict "$APP" \
  || echo "WARNING: deep verify failed (usually the bundled Chromium) — app signature itself is valid."

echo
echo "Done. App bundle: $APP  ($(lipo -archs "$APP/Contents/MacOS/My Maps Generator" 2>/dev/null || echo '?'))"
echo "Run ./build_dmg.sh to wrap it into a distributable .dmg."
