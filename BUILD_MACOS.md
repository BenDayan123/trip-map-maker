# Building the macOS app + installer

Mac counterpart of `build_exe.bat` / `build_installer.bat`. Produces
`My Maps Generator.app` and a drag-to-install `TripMapMaker.dmg`.

> **Must be built on a Mac.** PyInstaller is not a cross-compiler — you can't
> build the macOS app from Windows. The `.app` matches the CPU of the build
> machine (Apple Silicon `arm64` or Intel `x86_64`); build on each arch you want
> to ship, or on Apple Silicon and let Rosetta cover Intel.

## One-time setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

(No `streamlit-desktop-app` here — unlike the Windows build, `build_app.sh`
freezes our own `desktop.py` launcher and never imports it.)

`build_app.sh` installs Chromium itself (with `PLAYWRIGHT_BROWSERS_PATH=0`, so it
lands inside the `playwright` package and gets bundled into the `.app`, ~150MB).
Users then need no browser of their own — don't run a plain `playwright install`
first, that one goes to `~/Library/Caches/ms-playwright` and is *not* packaged.
The build then launches the bundled Chromium headless and **fails** if it doesn't
run, so a mangled copy, a missing exec bit, or a bad ad-hoc signature can't ship.
(Note `PLAYWRIGHT_BROWSERS_PATH=0` installs into your `site-packages`, and
`--collect-all playwright` bundles whatever browsers are in there — if you ever
ran it without the `chromium` argument you'll be shipping firefox and webkit too.)

## Build

```bash
./build_app.sh      # -> dist/My Maps Generator.app
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
xattr -dr com.apple.quarantine "/Applications/My Maps Generator.app"
```

To ship without that step you'd need an Apple Developer ID cert to `codesign`
and `notarytool`-notarize the app — out of scope here.

## Where user data lives

Keys, the Google login profile, and tokens are stored under
`~/Library/Application Support/TripMapMaker`, so they survive restarts and
updates (see `gmap_planner/paths.py`).
