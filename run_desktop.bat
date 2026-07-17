@echo off
REM Fast dev run: open the app in its desktop window straight from source
REM (no PyInstaller freeze, no installer). See run_desktop.py.
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

python -c "import streamlit_desktop_app" 2>nul || python -m pip install streamlit-desktop-app

python run_desktop.py
