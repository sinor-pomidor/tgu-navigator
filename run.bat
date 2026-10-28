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

rem --- hidden background workers (started by :pip / :pipuser below) ---------
if "%~1"=="_pip"   goto :work_pip
if "%~1"=="_pipuser" goto :work_pipuser

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
echo   Live progress bar below shows real percent and speed:
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download-python.ps1"
if errorlevel 1 goto :download_failed

call :bar_wait 20 "Extracting files"
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
    echo   Installing packages. The bar counts packages as pip installs them.
    "!APP_PY!" -m pip install --upgrade pip setuptools --disable-pip-version-check >nul 2>nul
    if errorlevel 1 goto :userinstall
    del .pip-ok .pip-fail >nul 2>nul
    set "PK_PYDIR=.venv\Lib"
    start "" /b "%~f0" _pip
    call :pkgbar
    if exist .pip-fail goto :userinstall
    if not exist .pip-ok goto :userinstall
    del .pip-ok .pip-fail .pip-step.log >nul 2>nul
    type nul > "!APP_PY!\Lib\site-packages\.tgu-deps-ok"
) else (
    echo   Packages already installed - skipping this step.
)
goto :dbready

:userinstall
"%PY%" -m ensurepip --upgrade >nul 2>nul
echo   Installing packages (fallback mode), please wait...
del .pip-ok .pip-fail >nul 2>nul
for /f "usebackq tokens=* delims=" %%P in (`"%PY%" -c "import site;print(site.getusersitepackages())" 2^>nul`) do set "PK_PYDIR=%%P"
start "" /b "%~f0" _pipuser
call :pkgbar
if exist .pip-ok (
    del .pip-ok .pip-fail .pip-step.log >nul 2>nul
    goto :dbready
)
echo   [ERROR] Could not install dependencies.
echo   Check your internet connection and run this file again.
echo   If the message mentions "cl.exe" or "Microsoft Visual C++", your Python
echo   is probably older than 3.9. Install a newer one from python.org
echo   (tick "Add python.exe to PATH") and double-click run.bat again.
pause
exit /b 1

rem ---------------------------------------------------------------------------
rem Database preparation: schema migration + catalog load, each shown with
rem its own built-in progress bar (app.progress wraps the long command).
rem Skipped when .tgu-db-ready marker exists (fast repeated launches).
rem ---------------------------------------------------------------------------
:dbready
if exist ".venv\Lib\site-packages\.tgu-db-ready" goto :env_ready
if exist ".tgu-user-db-ready" goto :env_ready
echo   Preparing database: migrating schema...
"!APP_PY!" -m app.progress --total 5 --label "Schema migration" --timeout 120 -- "!APP_PY!" -m app.migrations.add_origin_fields
if errorlevel 1 echo   [WARN] Migration did not finish - the server will fix the schema at startup.
echo   Loading opportunities catalog...
"!APP_PY!" -m app.progress --total 20 --label "Catalog load" --timeout 180 -- "!APP_PY!" -m app.seed
if errorlevel 1 echo   [WARN] Catalog was not loaded - the server will seed the DB at startup.
type nul > ".tgu-db-ready.tmp"
if exist ".venv\Lib\site-packages\.tgu-deps-ok" (
    type nul > ".venv\Lib\site-packages\.tgu-db-ready"
) else (
    type nul > ".tgu-user-db-ready"
)
del ".tgu-db-ready.tmp" >nul 2>nul

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
rem Step 4. Wait for startup (progress bar) and open browser
rem ---------------------------------------------------------------------------
echo.
echo [Step 4/4] Waiting for the site to come up...
set /a W_T=0
:wloop
set /a W_PCT=W_T*100/30
if %W_PCT% gtr 97 set W_PCT=97
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri http://127.0.0.1:8000/health -UseBasicParsing -TimeoutSec 1).StatusCode } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 set W_PCT=100
set /a W_FILLED=W_PCT*30/100
set "W_BAR="
for /l %%i in (1,1,30) do if %%i leq %W_FILLED% (set "W_BAR=!W_BAR!#") else (set "W_BAR=!W_BAR!-")
echo   [!W_BAR!] !W_PCT!%%
if not errorlevel 1 goto wok
set /a W_T+=1
if %W_T% geq 30 goto wtimeout
timeout /t 1 /nobreak >nul
goto wloop
:wtimeout
echo   [WARN] Server did not answer within 30 sec - opening the page anyway.
:wok
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

rem ---------------------------------------------------------------------------
rem :pkgbar - live progress bar driven by counting installed package folders.
rem Exits when worker writes .pip-ok or .pip-fail (or after ~6 min timeout).
rem ---------------------------------------------------------------------------
:pkgbar
set /a PK_MAX=45
set /a PK_T=0
:pkloop
set "PK_N=0"
for /f "usebackq tokens=* delims=" %%C in (`dir /b /ad "!PK_PYDIR!" 2^>nul ^| find /c /v ""`) do set "PK_N=%%C"
set /a PK_PCT=PK_N*100/PK_MAX
if !PK_PCT! gtr 97 set PK_PCT=97
if exist .pip-ok set PK_PCT=100
if exist .pip-fail set PK_PCT=100
set /a PK_FILLED=PK_PCT*30/100
set "PK_BAR="
for /l %%i in (1,1,30) do if %%i leq !PK_FILLED! (set "PK_BAR=!PK_BAR!#") else (set "PK_BAR=!PK_BAR!-")
echo   [!PK_BAR!] !PK_PCT!%%  (!PK_N! of ~!PK_MAX! packages)
if exist .pip-ok exit /b 0
if exist .pip-fail exit /b 0
set /a PK_T+=1
if %PK_T% geq 180 exit /b 0
timeout /t 2 /nobreak >nul
goto pkloop

rem ---------------------------------------------------------------------------
rem :bar_wait <seconds> <label> - deterministic animated bar for short steps
rem ---------------------------------------------------------------------------
:bar_wait
setlocal EnableExtensions EnableDelayedExpansion
set /a BW_TOTAL=%~1
set /a BW_N=0
:bwloop
set /a BW_PCT=BW_N*100/BW_TOTAL
if !BW_PCT! gtr 100 set BW_PCT=100
set /a BW_FILLED=BW_PCT*20/100
set "BW_BAR="
for /l %%i in (1,1,20) do if %%i leq !BW_FILLED! (set "BW_BAR=!BW_BAR!#") else (set "BW_BAR=!BW_BAR!-")
echo   [!BW_BAR!] !BW_PCT!%%  %~2
set /a BW_N+=1
if !BW_N! geq !BW_TOTAL! endlocal & exit /b 0
timeout /t 1 /nobreak >nul
goto bwloop

rem ---------------------------------------------------------------------------
rem Hidden workers: run this same file with _pip / _pipuser argument.
rem They install requirements.txt and leave a marker file for :pkgbar.
rem ---------------------------------------------------------------------------
:work_pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check > .pip-step.log 2>&1
if errorlevel 1 (type nul > .pip-fail) else (type nul > .pip-ok)
exit /b 0

:work_pipuser
%PY% -m pip install --user -r requirements.txt --disable-pip-version-check > .pip-step.log 2>&1
if errorlevel 1 (type nul > .pip-fail) else (type nul > .pip-ok)
exit /b 0
