# Building the macOS app + installer

Mac counterpart of `build_exe.bat` / `build_installer.bat`. Produces
`TripMapMaker.app` and a drag-to-install `TripMapMaker.dmg`.

> **Must be built on a Mac.** PyInstaller is not a cross-compiler — you can't
> build the macOS app from Windows. The `.app` matches the CPU of the build
> machine (Apple Silicon `arm64` or Intel `x86_64`); build on each arch you want
> to ship, or on Apple Silicon and let Rosetta cover Intel.

## One-time setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt streamlit-desktop-app
playwright install chromium      # optional — publishing can drive installed Google Chrome instead
```

## Build

```bash
./build_app.sh      # -> dist/TripMapMaker.app
./build_dmg.sh      # -> TripMapMaker.dmg
```

`build_app.sh` bundles the app with the blue/light theme and the `icon.icns`
map-pin icon (shown on the Dock, window, and .app in Finder). `build_dmg.sh`
wraps it into a `.dmg` whose window shows the app next to an **Applications**
shortcut — users drag to install.

## First run (unsigned app)

The app isn't code-signed/notarized, so Gatekeeper blocks the first launch.
Either **right-click → Open** once, or run:

```bash
xattr -dr com.apple.quarantine /Applications/TripMapMaker.app
```

To ship without that step you'd need an Apple Developer ID cert to `codesign`
and `notarytool`-notarize the app — out of scope here.

## Where user data lives

Keys, the Google login profile, and tokens are stored under
`~/Library/Application Support/TripMapMaker`, so they survive restarts and
updates (see `gmap_planner/paths.py`).
