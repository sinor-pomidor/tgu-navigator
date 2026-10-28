@echo off
rem ============================================================================
rem  TGU Navigator - Docker install (Windows)
rem  Use this ONLY if you have Docker Desktop installed.
rem  If not - just double-click run.bat instead (no Docker needed).
rem  Messages are in English on purpose: non-ASCII text in .bat files
rem  breaks on some Windows codepages.
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   TGU Navigator - Docker setup
echo ============================================================

rem ---------------------------------------------------------------------------
rem Step 1. Check Docker
rem ---------------------------------------------------------------------------
echo.
echo [Step 1/5] Checking Docker...
where docker >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] Docker was not found.
    echo   You do NOT need it: close this window and double-click run.bat instead.
    echo   If you really want the Docker version: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] Docker is installed but NOT running.
    echo   Open Docker Desktop, wait until its status is green ^(Engine running^),
    echo   then run this file again.
    pause
    exit /b 1
)
echo   [OK] Docker works.

rem ---------------------------------------------------------------------------
rem Step 2. Create .env from the sample if missing
rem ---------------------------------------------------------------------------
echo.
echo [Step 2/5] Configuration (.env)...
if exist .env (
    echo   [OK] .env already exists - keeping it as is.
) else (
    copy .env.example .env >nul
    echo   [OK] Created .env from the sample. Everything works WITHOUT keys.
    echo        For the Telegram bot later - put the token into .env.
)

rem ---------------------------------------------------------------------------
rem Step 3. Build and start containers
rem ---------------------------------------------------------------------------
echo.
echo [Step 3/5] Building and starting containers (database + site)...
echo          First run downloads images and builds the app - it can take
echo          several minutes. Docker prints its own progress below,
echo          so it is normal that this step is not instant.
docker compose down --remove-orphans >nul 2>nul
docker compose up --build -d
if errorlevel 1 (
    echo   [ERROR] Containers did not start. See the text above.
    pause
    exit /b 1
)
echo   [OK] Containers are running.

rem ---------------------------------------------------------------------------
rem Step 4. Wait for the API and load the catalog
rem ---------------------------------------------------------------------------
echo.
echo [Step 4/5] Waiting for the site to come up...
set /a TRY=0
:waitloop
set /a PCT=(TRY+1)*100/60
if %PCT% gtr 100 set PCT=100
set /a FILLED=PCT*30/100
set "BAR="
for /l %%i in (1,1,30) do if %%i leq %FILLED% (set "BAR=!BAR!#") else (set "BAR=!BAR! ")
echo   [!BAR!] !PCT!%%  (~%TRY% sec of ~120)
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing -TimeoutSec 2).StatusCode } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto healthok
set /a TRY+=1
if %TRY% geq 60 goto healthfail
timeout /t 2 /nobreak >nul
goto waitloop

:healthfail
echo   [ERROR] The site did not come up within 2 minutes. Last log lines:
docker compose logs app --tail 20
pause
exit /b 1

:healthok
echo   [OK] API responds: /health - ok
docker compose exec -T app python -m app.seed
if errorlevel 1 (
    echo   [ERROR] Could not load the catalog.
    pause
    exit /b 1
)
echo   [OK] Opportunities catalog loaded into the database.

rem ---------------------------------------------------------------------------
rem Step 5. Done
rem ---------------------------------------------------------------------------
echo.
echo [Step 5/5] Done!
echo.
echo   ============================================================
echo     PROJECT IS INSTALLED AND RUNNING
echo   ============================================================
echo.
echo     Web interface:  http://localhost:8000/
echo     API docs:       http://localhost:8000/docs
echo.
echo   Opening the page in your browser now...
start "" http://localhost:8000/
echo.
echo   Useful commands (run them in this folder, in a cmd window):
echo     stop project:     docker compose stop
echo     start again:      docker compose start
echo     view logs:        docker compose logs -f app
echo     reload catalog:   docker compose exec app python -m app.seed
echo.
echo   Telegram bot (once the token is in .env):
echo     docker compose exec app python -m app.bot.bot
echo.
pause
endlocal
