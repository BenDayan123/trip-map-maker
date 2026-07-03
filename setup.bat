@echo off
REM One-time setup: build a venv, install deps + the Playwright browser.
REM Double-click this once after installing Python 3.12.
cd /d "%~dp0"

echo ============================================
echo   Trip Map Maker - one-time setup
echo ============================================
echo.

REM Find a Python launcher (prefer the 3.12 launcher, fall back to python).
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY=py -3.12"
) else (
    set "PY=python"
)

echo [1/3] Creating virtual environment (.venv)...
%PY% -m venv .venv
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: could not create the venv. Is Python 3.12 installed?
    echo Download it from https://www.python.org/downloads/
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo [2/3] Installing Python packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo ERROR: pip install failed. See the messages above.
    pause
    exit /b 1
)

echo [3/3] Installing the Chromium browser for Playwright...
python -m playwright install chromium
if %ERRORLEVEL% neq 0 (
    echo ERROR: playwright install failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Setup complete.
echo ============================================
echo Next steps:
echo   1. Put your API keys in .streamlit\secrets.toml
echo      (copy .streamlit\secrets.toml.example and fill it in).
echo   2. Double-click login.bat and sign in to Google once.
echo   3. Every day: double-click run.bat.
echo.
pause
