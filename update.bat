@echo off
REM Get the latest version. Your keys and Google login are NOT touched
REM (secrets.toml, token.json, credentials.json, .pw-profile are all private).
cd /d "%~dp0"

where git >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Git is not installed, so auto-update isn't available.
    echo Install Git from https://git-scm.com/download/win and try again.
    pause
    exit /b 1
)

echo Pulling the latest version...
git pull --ff-only
if %ERRORLEVEL% neq 0 (
    echo.
    echo Update could not be applied automatically. Contact the developer.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Run setup.bat first.
    pause
    exit /b 1
)

echo Updating packages...
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt

echo.
echo Update complete. Double-click run.bat to start.
pause
