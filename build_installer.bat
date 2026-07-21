@echo off
REM Compile the Windows installer (installer\TripMapMaker-Setup.exe).
REM Prereqs: run build_exe.bat first, and install Inno Setup 6.
cd /d "%~dp0"

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 not found.
    echo Install it from https://jrsoftware.org/isdl.php  then run this again.
    pause
    exit /b 1
)

if not exist "dist\My Maps Generator\My Maps Generator.exe" (
    echo The app isn't built yet. Run build_exe.bat first.
    pause
    exit /b 1
)

"%ISCC%" installer.iss
if %ERRORLEVEL% neq 0 (
    echo Installer build failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo Done. Hand this file to the admin: installer\TripMapMaker-Setup.exe
pause
