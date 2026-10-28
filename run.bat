@echo off
rem ============================================================================
rem  TGU Navigator - one-file launch WITHOUT Docker (Windows)
rem  Just double-click this file. No Python needed for the first run:
rem  it downloads a small portable Python into .\.pyportable automatically.
rem  All messages are in English on purpose: batch files with non-ASCII
rem  text break on some Windows codepages (that was bug #123).
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PORTABLE_DIR=%~dp0.pyportable"
set "PORTABLE_PY=%PORTABLE_DIR%\python.exe"

echo.
echo ============================================================
echo   TGU Navigator - simple launch (no Docker, no install)
echo ============================================================

rem ---------------------------------------------------------------------------
rem Step 1. Find Python: system python/py first, then local portable copy
rem ---------------------------------------------------------------------------
echo.
echo [Step 1/4] Checking Python...
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if defined PY (
    %PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if errorlevel 1 set "PY="
)
if not defined PY (
    if exist "%PORTABLE_PY%" set "PY=%PORTABLE_PY%"
)
if defined PY goto :py_ok

echo   Python not found on this PC. Downloading portable Python...
echo   (one-time download, about 25 MB, takes 1-3 minutes)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; $ok=$false; foreach($tls in @('Tls12','Tls11','Tls')){ try{ [Net.ServicePointManager]::SecurityProtocol=$tls; Invoke-WebRequest -Uri 'https://github.com/indygreg/python-build-standalone/releases/download/20240814/cpython-3.11.9+20240814-x86_64-pc-windows-msvc-shared-install_only.tar.gz' -OutFile '%TEMP%\tgu-py.tar.gz' -UseBasicParsing; $ok=$true; break } catch {} }; if(-not $ok){ exit 1 }"
if errorlevel 1 goto :download_failed

mkdir "%PORTABLE_DIR%" >nul 2>nul
tar -xf "%TEMP%\tgu-py.tar.gz" -C "%PORTABLE_DIR%" --strip-components=1
if not exist "%PORTABLE_PY%" goto :download_failed
del "%TEMP%\tgu-py.tar.gz" >nul 2>nul
set "PY=%PORTABLE_PY%"
echo   [OK] Portable Python installed.
goto :py_ok

:download_failed
echo   [ERROR] Could not download Python automatically.
echo   Please install Python once manually:
echo     1. Open https://www.python.org/downloads/
echo     2. Run the installer and TICK the box "Add python.exe to PATH"
echo     3. Finish installation and double-click this file again
pause
exit /b 1

:py_ok
"%PY%" --version 2>nul || %PY% --version
echo   [OK] Python is ready.

rem ---------------------------------------------------------------------------
rem Step 2. Virtual environment + dependencies (first run takes 2-3 minutes)
rem ---------------------------------------------------------------------------
echo.
echo [Step 2/4] Preparing environment (first run takes 2-3 minutes)...
if not exist ".venv\" (
    "%PY%" -m venv .venv
    if errorlevel 1 (
        echo   [ERROR] Could not create virtual environment.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools --quiet --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo   [ERROR] Could not install dependencies.
    echo   Check your internet connection and run this file again.
    pause
    exit /b 1
)
echo   [OK] Environment ready.

rem ---------------------------------------------------------------------------
rem Step 3. Start server in a separate window
rem ---------------------------------------------------------------------------
echo.
echo [Step 3/4] Starting server in a separate window...
(
echo @echo off
echo cd /d "%%~dp0"
echo ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) > .run-server.bat
start "TGU Navigator server" cmd /k .run-server.bat
echo   [OK] Server is starting (log window opened separately).

rem ---------------------------------------------------------------------------
rem Step 4. Wait for startup and open browser
rem ---------------------------------------------------------------------------
echo.
echo [Step 4/4] Waiting for startup (a few seconds)...
timeout /t 8 /nobreak >nul
start "" http://localhost:8000/

echo.
echo ============================================================
echo   DONE! The browser should open the Navigator page.
echo   Address: http://localhost:8000
echo.
echo   How to use:
echo     - type a question about TGU projects/grants/events
echo     - if the page did not open, go to the address above
echo.
echo   To STOP the project: close the black "TGU Navigator server" window.
echo   To start again: just double-click run.bat.
echo ============================================================
echo.
pause
exit /b 0
