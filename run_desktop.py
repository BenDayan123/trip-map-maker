"""Fast dev launcher — run the app in its real desktop window, no build.

Opens the same pywebview window the packaged exe uses, but running the Streamlit
app straight from source: no PyInstaller freeze, no Inno Setup step, ~seconds to
start, and hot-reload on save. Use this for day-to-day development instead of
build_exe.bat / build_installer.bat (those are only for producing the installer).

    pip install -r requirements.txt   # once
    python run_desktop.py

Uses the same desktop.py launcher the packaged .app is frozen from (bounded
shutdown so closing the window actually quits), with server.runOnSave for
hot-reload on save.
"""

import multiprocessing

import desktop

if __name__ == "__main__":
    multiprocessing.freeze_support()
    desktop.start(
        options={"server.runOnSave": "true"},  # auto-reload on file save
        title="My Maps Generator (dev)",
    )
