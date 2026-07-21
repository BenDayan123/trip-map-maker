#!/usr/bin/env bash
# Build the standalone macOS app bundle (dist/My Maps Generator.app).
#
# Mac counterpart of build_exe.bat. PyInstaller is NOT a cross-compiler, so this
# must run ON a Mac (Apple Silicon or Intel) with Python 3.11+ installed. The
# resulting .app matches the arch of the machine that builds it.
#
# One-time:  pip install -r requirements.txt streamlit-desktop-app
#            playwright install chromium      # only if you don't drive installed Chrome
# Then:      ./build_app.sh                   # -> dist/My Maps Generator.app
#            ./build_dmg.sh                    # -> TripMapMaker.dmg (drag-to-install)
set -euo pipefail
cd "$(dirname "$0")"

if [ -d ".venv/bin" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

python -c "import streamlit_desktop_app" 2>/dev/null || python -m pip install streamlit-desktop-app

streamlit-desktop-app build streamlit_app.py --name "My Maps Generator" \
  --icon icon.icns \
  --pyinstaller-options --noconfirm --windowed \
    --collect-all playwright \
    --collect-all google \
    --collect-all googleapiclient \
    --collect-all google_auth_oauthlib \
    --collect-all gspread \
    --add-data "gmap_planner:gmap_planner" \
    --add-data "pages:pages" \
  --streamlit-options --theme.base=light "--theme.primaryColor=#2563EB"

# Trim ~90MB of unused Google API discovery docs; keep only Drive (the only API
# this app calls via googleapiclient). Safe: build('drive','v3') reads these.
DOCS="dist/My Maps Generator.app/Contents/Resources/googleapiclient/discovery_cache/documents"
[ -d "$DOCS" ] || DOCS="dist/My Maps Generator/_internal/googleapiclient/discovery_cache/documents"
if [ -d "$DOCS" ]; then
  echo "Trimming unused Google API discovery docs..."
  find "$DOCS" -type f -name '*.json' ! -name 'drive.v2.json' ! -name 'drive.v3.json' -delete
fi

echo
echo "Done. App bundle: dist/My Maps Generator.app"
echo "Run ./build_dmg.sh to wrap it into a distributable .dmg."
