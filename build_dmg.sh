#!/usr/bin/env bash
# Wrap dist/My Maps Generator.app into a distributable TripMapMaker.dmg.
#
# Uses only hdiutil (ships with macOS) — no Homebrew/extra tools. The DMG opens
# to the app next to an Applications shortcut, so the user just drags to install.
# Run build_app.sh first.
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/My Maps Generator.app"
VOL="My Maps Generator"
DMG="TripMapMaker.dmg"
STAGING="dist/dmg"

if [ ! -d "$APP" ]; then
  echo "Error: $APP not found. Run ./build_app.sh first." >&2
  exit 1
fi

rm -rf "$STAGING" "$DMG"
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
