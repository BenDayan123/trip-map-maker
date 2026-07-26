#!/usr/bin/env bash
# Wrap dist/My Maps Generator.app into a distributable TripMapMaker.dmg.
#
# Uses only hdiutil (ships with macOS) — no Homebrew/extra tools. The DMG opens
# to the app next to an Applications shortcut, so the user just drags to install.
# Run build_app.sh first.
#
# Output location (default = this folder). To drop the .dmg straight into a
# shared folder — e.g. the Windows "D:\MacOS\Shared Data" mounted inside a Mac
# VM — pass the mount path as the first arg or set DMG_OUT_DIR:
#     ./build_dmg.sh "/Volumes/Shared Data"
#     DMG_OUT_DIR="$HOME/Parallels Shared Folders/Home/MacOS/Shared Data" ./build_dmg.sh
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/My Maps Generator.app"
VOL="My Maps Generator"
STAGING="dist/dmg"
OUT_DIR="${1:-${DMG_OUT_DIR:-$(pwd)}}"
DMG="$OUT_DIR/TripMapMaker.dmg"

if [ ! -d "$APP" ]; then
  echo "Error: $APP not found. Run ./build_app.sh first." >&2
  exit 1
fi
mkdir -p "$OUT_DIR"

rm -rf "$STAGING"
rm -f "$DMG"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"   # drag-to-install target

hdiutil create -volname "$VOL" \
  -srcfolder "$STAGING" \
  -ov -format UDZO \
  "$DMG"

rm -rf "$STAGING"
echo
echo "Done. Installer: $DMG"
echo "Distribute this file; users drag My Maps Generator into Applications."
