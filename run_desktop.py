"""Fast dev launcher — run the app in its real desktop window, no build.

Opens the same pywebview window the packaged exe uses, but running the Streamlit
app straight from source: no PyInstaller freeze, no Inno Setup step, ~seconds to
start, and hot-reload on save. Use this for day-to-day development instead of
build_exe.bat / build_installer.bat (those are only for producing the installer).

    pip install -r requirements.txt streamlit-desktop-app   # once
    python run_desktop.py

The theme flags mirror the packaged build so the window looks identical, and
server.runOnSave makes edits reload automatically.
"""

from streamlit_desktop_app import start_desktop_app

if __name__ == "__main__":
    start_desktop_app(
        "streamlit_app.py",
        title="Trip Map Maker (dev)",
        options={
            "theme.base": "light",
            "theme.primaryColor": "#2563EB",
            "server.runOnSave": "true",  # auto-reload on file save
        },
    )
