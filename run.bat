@echo off
REM Daily launcher: start the app (a browser tab opens automatically).
REM Double-click this every time you want to use Trip Map Maker.
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Run setup.bat first.
    pause
    exit /b 1
)

REM Pull the latest version if this is a git clone and we're online.
REM Never blocks launch - failures (offline, no git) are ignored.
where git >nul 2>&1
if %ERRORLEVEL%==0 (
    echo Checking for updates...
    git pull --ff-only 2>nul
)

call ".venv\Scripts\activate.bat"
echo Starting Trip Map Maker - your browser will open shortly.
echo Close this window to stop the app.
streamlit run streamlit_app.py
