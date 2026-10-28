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
echo   A progress bar is shown below: [====>                ] 17%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0.download-python.ps1"
if errorlevel 1 goto :download_failed

echo   Extracting files (a few seconds)...
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
set "APP_PY=%PY%"
if not exist ".venv\Scripts\python.exe" (
    "%PY%" -m venv .venv > .venv-error.log 2>&1
    if not exist ".venv\Scripts\python.exe" (
        echo   [WARN] Virtual environment could not be created.
        echo   Reason (last lines):
        powershell -NoProfile -Command "Get-Content .venv-error.log -Tail 4"
        echo   Falling back to user-level install (works fine, just less isolated).
        rmdir /s /q .venv >nul 2>nul
        del .venv-error.log >nul 2>nul
        goto :userinstall
    )
    del .venv-error.log >nul 2>nul
)
set "APP_PY=.venv\Scripts\python.exe"
if not exist "!APP_PY!\Lib\site-packages\.tgu-deps-ok" (
    echo   Installing packages, please wait (you will see progress below)...
    "!APP_PY!" -m pip install --upgrade pip setuptools --disable-pip-version-check
    if errorlevel 1 goto :userinstall
    "!APP_PY!" -m pip install -r requirements.txt --disable-pip-version-check
    if errorlevel 1 goto :userinstall
    type nul > "!APP_PY!\Lib\site-packages\.tgu-deps-ok"
) else (
    echo   Packages already installed - skipping this step.
)
goto :env_ready

:userinstall
"%PY%" -m ensurepip --upgrade >nul 2>nul
echo   Installing packages, please wait (you will see progress below)...
"%PY%" -m pip install --user -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo   [ERROR] Could not install dependencies.
    echo   Check your internet connection and run this file again.
    echo   If the message mentions "cl.exe" or "Microsoft Visual C++", your Python
    echo   is probably older than 3.9. Install a newer one from python.org
    echo   (tick "Add python.exe to PATH") and double-click run.bat again.
    pause
    exit /b 1
)
set "APP_PY=%PY%"

:env_ready
echo   [OK] Environment ready.

rem ---------------------------------------------------------------------------
rem Step 3. Start server in a separate window
rem ---------------------------------------------------------------------------
echo.
echo [Step 3/4] Starting server in a separate window...
(
echo @echo off
echo cd /d "%%~dp0"
echo !APP_PY! -m uvicorn app.main:app --host 127.0.0.1 --port 8000
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
