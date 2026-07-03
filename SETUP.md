# Trip Map Maker — Admin Setup (Windows)

Run the app on your own computer. Set up **once**, then it's a double-click every day.
Playwright uses your real Chrome/Edge, and your keys + Google login are saved locally, so
nothing needs re-entering.

## Easiest: the standalone app (no Python needed)

If the developer gave you a **TripMapMaker** folder (or zip):

1. Unzip it anywhere (e.g. your Desktop).
2. Double-click **`TripMapMaker.exe`** — the app opens in its own window.
3. Open **🔑 Settings (API keys)** in the left sidebar, paste your Gemini + Geocoding
   keys, click **Save keys**. (Stored on your PC — done once.)
4. To publish maps to Google My Maps, enable **Publish to My Maps** and click
   **Log in to Google** once. Your login is remembered.

Your keys, login, and settings are saved under `%APPDATA%\TripMapMaker`, so they survive
app restarts and updates. That's it — everything below is the alternative "run from
source" route for developers.

---


## First-time setup (once)

1. **Install Python 3.12** — https://www.python.org/downloads/
   On the first installer screen, tick **"Add Python to PATH"**.
   (Optional but recommended: install **Git** — https://git-scm.com/download/win — so
   updates are one click.)

2. **Double-click `setup.bat`.**
   It builds an isolated environment, installs everything, and downloads the browser
   Playwright needs. Wait for **"Setup complete."**

3. **Add your keys.** In the `.streamlit` folder, copy `secrets.toml.example` to
   `secrets.toml` and fill in:
   - `GOOGLE_API_KEY` — Gemini key (Google AI Studio / Cloud console)
   - `GEO_API_KEY` — Geocoding key (Google Cloud console)
   - (optional) the analytics / usage-gauge values.

4. **Double-click `login.bat`.** A Chrome window opens — sign in to your Google
   account once. This is only needed if you want to **publish** maps to Google My Maps.
   The login is saved; you won't be asked again.

5. **(Only if you'll share maps)** Put your Drive `credentials.json` in this folder, or
   upload it in the app under **Publish to My Maps**. The first time you share, a Google
   consent window appears once and is then remembered.

## Every day

**Double-click `run.bat`** (or `run.vbs` for no console window). Your browser opens the
app. Upload an itinerary (PDF/TXT), get your map files, and optionally publish to My Maps.
Close the window to stop it.

Tip: right-click `run.vbs` → **Send to → Desktop (create shortcut)** for a clean icon.

## Getting updates

When the developer ships a new version, **double-click `update.bat`** — it pulls the
latest and refreshes packages. Your keys, Google login, and shared-map access are
**never** touched. (If Git is installed, `run.bat` also auto-updates on launch.)

## The "Setup status" panel

Open **⚙️ Setup status** in the app's left sidebar to see, at a glance, which one-time
items are done (✅) and which are still needed (⚪).
