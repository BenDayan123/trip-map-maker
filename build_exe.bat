@echo off
REM Build the standalone desktop executable (dist\TripMapMaker\TripMapMaker.exe).
REM For the developer, not the admin. Requires: pip install streamlit-desktop-app
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

python -c "import streamlit_desktop_app" 2>nul || python -m pip install streamlit-desktop-app

REM Theme is passed as Streamlit CLI options (config.toml isn't on the frozen
REM app's config search path), forcing the blue primary color + light base.
streamlit-desktop-app build streamlit_app.py --name TripMapMaker ^
  --pyinstaller-options --noconfirm --windowed ^
  --collect-all playwright ^
  --collect-all google ^
  --collect-all googleapiclient ^
  --collect-all google_auth_oauthlib ^
  --collect-all gspread ^
  --add-data "gmap_planner;gmap_planner" ^
  --add-data "pages;pages" ^
  --streamlit-options --theme.base=light "--theme.primaryColor=#2563EB"

REM Trim ~90MB of unused Google API discovery docs; keep only Drive (the only
REM API this app calls via googleapiclient). Safe: build('drive','v3') reads these.
set "DOCS=dist\TripMapMaker\_internal\googleapiclient\discovery_cache\documents"
if exist "%DOCS%" (
    echo Trimming unused Google API discovery docs...
    for %%F in ("%DOCS%\*.json") do (
        if /I not "%%~nxF"=="drive.v2.json" if /I not "%%~nxF"=="drive.v3.json" del "%%F"
    )
)

echo.
echo Done. The app is in dist\TripMapMaker\ (zip that folder to distribute).
pause
