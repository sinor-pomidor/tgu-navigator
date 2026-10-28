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
rem Step 1. Find Python: system python/py, portable copy, then winget.
rem IMPORTANT: Microsoft Store ships a "python.exe" alias stub that prints
rem nothing and exits with an error - it must NOT be treated as real Python.
rem ---------------------------------------------------------------------------
echo.
echo [Step 1/4] Checking Python...
set "PY="

rem Portable copy from a previous run has top priority (fully ours).
if exist "%PORTABLE_PY%" (
    "%PORTABLE_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=%PORTABLE_PY%"
)

rem System python.exe / py.exe - verify it is REAL Python, not the Store stub.
if not defined PY (
    where python >nul 2>nul && (
        python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=python"
    )
)
if not defined PY (
    where py >nul 2>nul && (
        py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=py -3"
    )
)
if defined PY goto :py_ok

rem Python missing entirely -> try winget first (no PowerShell/.NET needed),
rem then fall back to downloading the official installer.
echo   Python not found on this PC. Trying automatic install via winget...
del ".download.log" >nul 2>nul
where winget >nul 2>nul && (
    echo   Method 1 of 2: winget install Python.Python.3.11 ...
    winget install --id Python.Python.3.11 -e --accept-source-agreements --accept-package-agreements --silent >".download.log" 2>&1
    if not errorlevel 1 set "DL_OK=winget"
)
if defined DL_OK (
    rem winget updated registry PATH; refresh it inside this window.
    for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul ^| find "Path"') do set "PATH=%%B;%PATH%"
    for %%V in (3.11 3.12 3.10) do if exist "%LOCALAPPDATA%\Programs\Python\%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\%%V\python.exe"
    if not defined PY where python >nul 2>nul && set "PY=python"
    if defined PY (
        "%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
        if not errorlevel 1 echo   [OK] Python installed via winget.
        if errorlevel 1 set "PY="
    )
    if defined PY goto :py_ok
)

echo   winget unavailable or failed. Downloading official installer...
call :download_python
if defined PY goto :py_ok
goto :download_failed

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
echo   Preparing database: migrating schema (bar below)...
rem NOTE: no app.progress wrapper here - it spawns a nested python that may
rem lose PYTHONPATH on portable Python and fail. The bar waits on the real
rem command instead; failures are non-fatal (the server seeds at startup).
start "" /b cmd /c ""!APP_PY!" -m app.migrations.add_origin_fields > .mig.log 2>&1 & echo %%ERRORLEVEL%%> .mig-code.tmp"
call :migbar
del .mig-code.tmp >nul 2>nul
powershell -NoProfile -Command "if (Test-Path .mig.log) { Get-Content .mig.log -Tail 4 }" >nul 2>nul
echo   Loading opportunities catalog (bar below)...
start "" /b cmd /c ""!APP_PY!" -m app.seed > .seed.log 2>&1 & echo %%ERRORLEVEL%%> .seed-code.tmp"
call :seedbar
del .seed-code.tmp >nul 2>nul
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
rem :migbar - animated bar while schema migration runs in background
rem (finishes when worker writes .mig-code.tmp, max ~120 sec).
rem ---------------------------------------------------------------------------
:migbar
setlocal EnableExtensions EnableDelayedExpansion
set /a MB_MAX=120
set /a MB_N=0
:mbloop
set /a MB_PCT=MB_N*100/MB_MAX
if !MB_PCT! gtr 97 set MB_PCT=97
if exist .mig-code.tmp set MB_PCT=100
set /a MB_FILLED=MB_PCT*30/100
set "MB_BAR="
for /l %%i in (1,1,30) do if %%i leq !MB_FILLED! (set "MB_BAR=!MB_BAR!#") else (set "MB_BAR=!MB_BAR!-")
echo   [!MB_BAR!] !MB_PCT!%%  Schema migration (!MB_N! sec elapsed)
if exist .mig-code.tmp endlocal & exit /b 0
set /a MB_N+=1
if !MB_N! geq !MB_MAX! endlocal & exit /b 0
timeout /t 1 /nobreak >nul
goto mbloop

rem ---------------------------------------------------------------------------
rem :seedbar - animated bar while catalog load runs in background
rem (finishes when worker writes .seed-code.tmp, max ~180 sec).
rem ---------------------------------------------------------------------------
:seedbar
setlocal EnableExtensions EnableDelayedExpansion
set /a SB_MAX=180
set /a SB_N=0
:sbloop
set /a SB_PCT=SB_N*100/SB_MAX
if !SB_PCT! gtr 97 set SB_PCT=97
if exist .seed-code.tmp set SB_PCT=100
set /a SB_FILLED=SB_PCT*30/100
set "SB_BAR="
for /l %%i in (1,1,30) do if %%i leq !SB_FILLED! (set "SB_BAR=!SB_BAR!#") else (set "SB_BAR=!SB_BAR!-")
echo   [!SB_BAR!] !SB_PCT!%%  Catalog load (!SB_N! sec elapsed)
if exist .seed-code.tmp endlocal & exit /b 0
set /a SB_N+=1
if !SB_N! geq !SB_MAX! endlocal & exit /b 0
timeout /t 1 /nobreak >nul
goto sbloop

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

rem ---------------------------------------------------------------------------
rem :download_python - fetch and run the official Python installer.
rem Three independent channels, each tried in order; real errors are written
rem to .download.log so the user sees WHY something failed:
rem   1. curl.exe  (shipped with Windows 10 1803+, no PowerShell/.NET needed)
rem   2. certutil  (built into every Windows since XP, dead simple)
rem   3. Invoke-WebRequest (last resort; catches its own errors)
rem On success sets PY and returns 0; otherwise returns 1.
rem ---------------------------------------------------------------------------
:download_python
set "DL_OK="
mkdir "%PORTABLE_DIR%" >nul 2>nul
set "SETUP_EXE=%PORTABLE_DIR%\python-setup.exe"
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

echo   Method 1 of 3: curl + python.org...
where curl.exe >nul 2>nul
if not errorlevel 1 (
    curl.exe --fail -sSL --retry 2 --max-time 900 -o "%SETUP_EXE%" "%PY_URL%" 2>>".download.log"
    if not errorlevel 1 set "DL_OK=curl"
)

if not defined DL_OK (
    echo   Method 2 of 3: certutil + python.org...
    certutil -urlcache -split -f "%PY_URL%" "%SETUP_EXE%" >>".download.log" 2>nul
    if not errorlevel 1 set "DL_OK=certutil"
)

if not defined DL_OK (
    echo   Method 3 of 3: PowerShell Invoke-WebRequest...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%SETUP_EXE%' -UseBasicParsing } catch { Add-Content -Path '.download.log' -Value $_.Exception.Message; exit 1 }" >nul 2>nul
    if not errorlevel 1 set "DL_OK=iwr"
)

if not defined DL_OK exit /b 1
if not exist "%SETUP_EXE%" exit /b 1

echo   Download finished (%DL_OK%). Installing Python silently (no admin)...
call :bar_wait 90 "Installing Python"
"%SETUP_EXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 >nul 2>nul
del "%SETUP_EXE%" >nul 2>nul

rem Locate the freshly installed interpreter (per-user location).
for %%V in (3.11 3.12 3.10) do (
    if exist "%LOCALAPPDATA%\Programs\Python\%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\%%V\python.exe"
)
if not defined PY (
    rem Installer updated registry PATH; refresh it inside this window.
    for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul ^| find "Path"') do set "PATH=%%B;%PATH%"
    where python >nul 2>nul && set "PY=python"
)
if not defined PY exit /b 1
"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
echo   [OK] Python installed automatically.
exit /b 0

:download_failed
echo   [ERROR] Could not install Python automatically.
echo   Possible reasons: no internet, proxy/firewall blocks downloads,
echo   or the download server is temporarily unavailable.
if exist ".download.log" (
    echo   --- Last error lines (from .download.log): ---
    powershell -NoProfile -Command "Get-Content '.download.log' -Tail 3" 2>nul
    echo   -----------------------------------------------
)
echo   Please install Python once manually - it takes 2 minutes:
echo     1. Open https://www.python.org/downloads/
echo     2. Run the installer and TICK the box "Add python.exe to PATH"
echo     3. Finish installation and double-click this file again
pause
exit /b 1
