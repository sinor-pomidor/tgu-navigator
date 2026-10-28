@echo off
chcp 65001 >nul
rem ============================================================================
rem  TGU Navigator - simple launch WITHOUT Docker (Windows)
rem  Just double-click this file.
rem ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   TGU Navigator - simple launch (no Docker needed)
echo ============================================================

echo.
echo [Step 1/4] Checking Python...
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo   [ERROR] Python not found.
    echo   Install Python 3.11 or newer: https://www.python.org/downloads/
    echo   IMPORTANT: tick "Add python.exe to PATH" during installation.
    echo   Then run this file again.
    pause
    exit /b 1
)
%PY% --version
echo   [OK] Python found.

echo.
echo [Step 2/4] Preparing environment (first run takes 2-3 minutes)...
if not exist ".venv\" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   [ERROR] Could not create virtual environment.
        pause
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo   [ERROR] Could not install dependencies.
    echo   Check your internet connection and run this file again.
    pause
    exit /b 1
)
echo   [OK] Environment ready.

echo.
echo [Step 3/4] Starting server in a separate window...
(
echo @echo off
echo cd /d "%~dp0"
echo call ".venv\Scripts\activate.bat"
echo python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) > .run-server.bat
start "TGU Navigator server" cmd /k .run-server.bat
echo   [OK] Server is starting (log window opened separately).

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

