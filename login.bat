@echo off
REM One-time Google sign-in for My Maps publishing. A Chrome window opens -
REM sign in with your Google account; the session is saved to .pw-profile\
REM and reused on every later run (no need to sign in again).
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Run setup.bat first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python main.py --login

echo.
pause
