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

# Fetch Chromium into a staging dir, to be copied into the .app AFTER PyInstaller
# runs (see below). ~150MB, worth it: the user needs no browser of their own.
#
# It must NOT be inside the playwright package: PyInstaller treats every collected
# Mach-O as a loose binary and re-signs each one, and codesign refuses the main
# executable of a nested .app ("bundle format unrecognized, invalid, or
# unsuitable") — which fails the whole build. Keep the browser away from
# --collect-all and hand it to the bundle ourselves.
BROWSERS_SRC="$PWD/build/ms-playwright"
TARGET_ARCH="$(python -c 'import platform; print(platform.machine())')"
PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_SRC" python -m playwright install chromium

# Playwright's node driver is a universal2 binary and downloads the browser for
# the arch it happens to RUN as, not the one we're building for — that shipped an
# arm64 browser inside an Intel app once, and nothing surfaces it until a user of
# that arch tries to publish. The browser dir is named after its arch, so check.
# (Only a cross-build can trip this; this build is native, see build-macos.yml.)
case "$TARGET_ARCH" in
  arm64) WANT_BROWSER="chrome-mac-arm64" ;;
  x86_64) WANT_BROWSER="chrome-mac-x64" ;;
  *) WANT_BROWSER="" ;;
esac
if [ -n "$WANT_BROWSER" ] && [ -z "$(find "$BROWSERS_SRC" -type d -name "$WANT_BROWSER" -print -quit)" ]; then
  echo "Error: Playwright fetched the wrong browser arch for a $TARGET_ARCH build." >&2
  echo "       Expected a '$WANT_BROWSER' directory under $BROWSERS_SRC, found:" >&2
  find "$BROWSERS_SRC" -maxdepth 2 -type d -name 'chrome-mac*' >&2
  exit 1
fi

# A leftover in-package install (an older build, or a manual
# `PLAYWRIGHT_BROWSERS_PATH=0 playwright install`) would still be collected and
# still break the build, with a codesign error that doesn't name the cause.
PKG_BROWSERS="$(python -c 'import inspect, os, playwright; print(os.path.join(os.path.dirname(inspect.getfile(playwright)), "driver", "package", ".local-browsers"))')"
if [ -d "$PKG_BROWSERS" ]; then
  echo "Error: browsers are installed inside the playwright package:" >&2
  echo "  $PKG_BROWSERS" >&2
  echo "PyInstaller cannot process a nested .app there. Remove it and re-run:" >&2
  echo "  rm -rf \"$PKG_BROWSERS\"" >&2
  exit 1
fi

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

APP="dist/My Maps Generator.app"

# Copy the browser in by hand, next to the collected `playwright` package — i.e.
# into sys._MEIPASS, which is what gmap_planner/mymaps.py `_bundled_browsers_dir()`
# resolves at runtime. `cp -R` preserves the nested .app's structure, symlinks and
# exec bits, none of which survive PyInstaller's binary processing.
MEIPASS="$(dirname "$(find "$APP/Contents" -maxdepth 3 -type d -name playwright -print -quit)")"
if [ -z "$MEIPASS" ] || [ ! -d "$MEIPASS" ]; then
  echo "Error: can't find the collected playwright package inside $APP." >&2
  exit 1
fi
echo "Copying Chromium into the bundle ($MEIPASS/ms-playwright)..."
rm -rf "$MEIPASS/ms-playwright"
cp -R "$BROWSERS_SRC" "$MEIPASS/ms-playwright"

# PyInstaller copies collected data files without their exec bit, so Playwright's
# node driver comes out non-executable ("Permission denied" at publish time).
# Must run BEFORE codesign — changing a file afterwards invalidates the signature.
echo "Restoring exec bits on the bundled Playwright driver..."
find "$APP" -type d -name driver -path '*playwright*' -exec chmod -R a+x {} +

# Ad-hoc codesign so Gatekeeper doesn't reject the unsigned app as "damaged" on
# Apple Silicon (no paid Developer ID — users still do a one-time Open Anyway,
# see INSTALL_MACOS.md). Signing the whole bundle also covers a build made in an
# Intel VM (native arch = x86_64), which then runs on Intel + Apple Silicon (via
# Rosetta 2). Done here so both the CI workflow and a local/VM build get a signed
# app from one place.
echo "Ad-hoc codesigning $APP ..."
codesign --force --deep --sign - "$APP"
# Top-level signature is what Gatekeeper checks — that one must pass. The deep
# pass also walks the bundled browser's own .app; warn, don't fail the build. The
# check that matters for the browser is the launch below.
codesign --verify --strict "$APP"
codesign --verify --deep --strict "$APP" \
  || echo "WARNING: deep verify failed (usually the bundled Chromium) — app signature itself is valid."

# Prove the bundled browser actually works, rather than that a directory with the
# right name exists. Runs AFTER codesign on purpose: an invalid ad-hoc signature
# on a nested Mach-O is killed on sight by Apple Silicon, and this launch is the
# check that catches it (the deep verify above only warns). Also catches the
# exec bits, a wrong arch, and a browser PyInstaller mangled on the way in.

# The browser's own .app directory inside a tree ($1). Playwright renamed this
# more than once (chrome-mac/Chromium.app, chrome-mac-arm64/Google Chrome for
# Testing.app), so match the stable part — the chrome-mac* dir — not the name.
# `find` prints a parent before its children, so the browser comes before its
# nested Helper .apps.
browser_app() {
  find "$1" -type d -name '*.app' -path '*chrome-mac*' -print 2>/dev/null | head -1
}

# The browser's main executable: the one file in the .app's MacOS dir.
browser_binary() {
  local app
  app="$(browser_app "$1")"
  [ -n "$app" ] && find "$app/Contents/MacOS" -maxdepth 1 -type f -print -quit
}

check_bundled_chromium() {
  local app="$1" browsers="$MEIPASS/ms-playwright" chrome
  if [ ! -d "$browsers" ]; then
    echo "Error: Chromium is not bundled where the app looks for it ($browsers)." >&2
    return 1
  fi
  chrome="$(browser_binary "$browsers")"
  if [ -z "$chrome" ]; then
    echo "Error: no browser executable under $browsers." >&2
    return 1
  fi
  echo "Launching the bundled browser to verify it runs..."
  "$chrome" --headless=new --disable-gpu --no-sandbox --dump-dom about:blank >/dev/null
  echo "  ok: $(lipo -archs "$chrome" 2>/dev/null || echo '?')  $chrome"
}
check_bundled_chromium "$APP"

echo
echo "Done. App bundle: $APP  ($(lipo -archs "$APP/Contents/MacOS/My Maps Generator" 2>/dev/null || echo '?'))"
echo "Run ./build_dmg.sh to wrap it into a distributable .dmg."
