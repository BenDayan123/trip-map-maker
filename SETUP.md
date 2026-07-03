# Trip Map Maker — Admin Guide (Windows)

You get a single installer, **`TripMapMaker-Setup.exe`**. No Python, no terminal.

## Install (once)

1. Double-click **`TripMapMaker-Setup.exe`** and click through the wizard.
   (It installs just for you — no admin password needed.)
2. It creates a **Trip Map Maker** shortcut on your Desktop and Start menu.

## First run

1. Open **Trip Map Maker** (Desktop / Start menu). The app opens in its own window.
2. In the left sidebar, open **🔑 Settings (API keys)**, paste your **Gemini** and
   **Geocoding** keys, and click **Save keys**. Done once — they're remembered.
3. To publish maps to Google My Maps, turn on **Publish to My Maps** and click
   **Log in to Google** once. Your sign-in is saved for next time.

Your keys, login, and settings are stored under `%APPDATA%\TripMapMaker`, so they
**survive app restarts and updates**.

## Everyday use

Open **Trip Map Maker**, drag in an itinerary (PDF or TXT), get your map files, and
optionally publish + share. Close the window to stop.

Check **⚙️ Setup status** in the sidebar to see, at a glance, what's configured (✅) and
what still needs doing (⚪).

## Updates

When the developer sends a **new `TripMapMaker-Setup.exe`**, just run it — it installs
over the old version. Your keys and Google login are untouched.

---

## For developers (run from source)

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run streamlit_app.py
```

Build the desktop app + installer (Windows):

```bat
pip install streamlit-desktop-app     :: one-time
build_exe.bat                         :: -> dist\TripMapMaker\
build_installer.bat                   :: -> installer\TripMapMaker-Setup.exe (needs Inno Setup 6)
```
