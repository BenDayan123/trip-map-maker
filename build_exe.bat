@echo off
REM Build the standalone desktop executable (dist\TripMapMaker\TripMapMaker.exe).
REM For the developer, not the admin. Requires: pip install streamlit-desktop-app
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Run setup.bat first, then: pip install streamlit-desktop-app
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"

python -c "import streamlit_desktop_app" 2>nul || python -m pip install streamlit-desktop-app

streamlit-desktop-app build streamlit_app.py --name TripMapMaker ^
  --pyinstaller-options --noconfirm ^
  --collect-all playwright ^
  --collect-all google ^
  --collect-all googleapiclient ^
  --collect-all google_auth_oauthlib ^
  --collect-all gspread ^
  --add-data "gmap_planner;gmap_planner" ^
  --add-data "pages;pages"

echo.
echo Done. The app is in dist\TripMapMaker\ (zip that folder to distribute).
pause
