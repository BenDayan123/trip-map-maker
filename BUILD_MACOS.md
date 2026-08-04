# Building the macOS app + installer

Mac counterpart of `build_exe.bat` / `build_installer.bat`. Produces
`My Maps Generator.app` and a drag-to-install `TripMapMaker.dmg`.

> **Must be built on a Mac.** PyInstaller is not a cross-compiler — you can't
> build the macOS app from Windows. The `.app` matches the CPU of the build
> machine, and releases are **Apple Silicon only** (the admins run Apple
> Silicon). To ship Intel again, build on a real Intel Mac — do not cross-build
> under Rosetta: Playwright's `universal2` node driver fetches the browser for
> the arch it runs as, so an Intel app built that way ships an arm64 browser
> that can't start. `build_app.sh` fails the build if that happens.

## One-time setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

(No `streamlit-desktop-app` here — unlike the Windows build, `build_app.sh`
freezes our own `desktop.py` launcher and never imports it.)

`build_app.sh` fetches Chromium itself into `build/ms-playwright` and copies it
into the `.app` **after** PyInstaller runs (~150MB), so users need no browser of
their own. It then launches that browser headless and **fails the build** if it
doesn't run — a missing exec bit, a wrong arch, or a bad ad-hoc signature can't
ship silently.

The copy happens after the freeze on purpose: PyInstaller re-signs every binary
it collects, and `codesign` rejects the main executable of a nested `.app`
("bundle format unrecognized, invalid, or unsuitable"), which fails the whole
build. So the browser must stay out of `--collect-all playwright`. If you ever
ran `PLAYWRIGHT_BROWSERS_PATH=0 playwright install`, browsers are sitting inside
your `playwright` package and will be collected — the build stops and tells you
which directory to delete.

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
