@echo off
chcp 65001 >nul
rem ============================================================================
rem  ТГУ: Навигатор возможностей — установка и запуск (Windows)
rem  Просто дважды кликни по этому файлу (или запусти в cmd: install.bat)
rem  Скрипт проверит Docker, создаст конфиг, соберёт контейнеры,
rem  загрузит каталог возможностей и покажет, куда заходить.
rem ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   ТГУ: Навигатор возможностей — установка
echo ============================================================

rem ---------------------------------------------------------------------------
rem Шаг 1. Проверяем Docker
rem ---------------------------------------------------------------------------
echo.
echo [Шаг 1/5] Проверка Docker...
where docker >nul 2>nul
if errorlevel 1 (
    echo   [ОШИБКА] Docker не найден.
    echo   Установи Docker Desktop: https://www.docker.com/products/docker-desktop/
    echo   Перезагрузи компьютер и запусти этот файл снова.
    pause
    exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
    echo   [ОШИБКА] Docker установлен, но НЕ запущен.
    echo   Открой приложение Docker Desktop, дождись зелёного статуса
    echo   ^(Engine running^) и запусти этот файл снова.
    pause
    exit /b 1
)
echo   [OK] Docker работает.

rem ---------------------------------------------------------------------------
rem Шаг 2. Создаём .env из образца, если его нет
rem ---------------------------------------------------------------------------
echo.
echo [Шаг 2/5] Конфигурация (.env)...
if exist .env (
    echo   [OK] .env уже существует — оставляю как есть.
) else (
    copy .env.example .env >nul
    echo   [OK] Создан .env из образца. Всё работает БЕЗ ключей (LLM_PROVIDER=mock).
    echo        Если позже захочешь Telegram-бота — допиши токен в файл .env.
)

rem ---------------------------------------------------------------------------
rem Шаг 3. Останавливаем старые контейнеры, собираем и запускаем новые
rem ---------------------------------------------------------------------------
echo.
echo [Шаг 3/5] Сборка и запуск контейнеров (база данных + сайт)...
echo          Это может занять несколько минут при первом запуске...
docker compose down --remove-orphans >nul 2>nul
docker compose up --build -d
if errorlevel 1 (
    echo   [ОШИБКА] Не удалось поднять контейнеры. См. текст выше.
    pause
    exit /b 1
)
echo   [OK] Контейнеры запущены.

rem ---------------------------------------------------------------------------
rem Шаг 4. Ждём готовности API и загружаем каталог
rem ---------------------------------------------------------------------------
echo.
echo [Шаг 4/5] Ожидание запуска сайта...
set /a TRY=0
:waitloop
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing -TimeoutSec 2).StatusCode } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto healthok
set /a TRY+=1
if %TRY% geq 60 goto healthfail
timeout /t 2 /nobreak >nul
goto waitloop

:healthfail
echo   [ОШИБКА] Сайт не поднялся за 2 минуты. Последние строки лога:
docker compose logs app --tail 20
pause
exit /b 1

:healthok
echo   [OK] API отвечает: /health - ok
docker compose exec -T app python -m app.seed
if errorlevel 1 (
    echo   [ОШИБКА] Не удалось загрузить каталог.
    pause
    exit /b 1
)
echo   [OK] Каталог возможностей загружен в базу.

rem ---------------------------------------------------------------------------
rem Шаг 5. Итог
rem ---------------------------------------------------------------------------
echo.
echo [Шаг 5/5] Готово!
echo.
echo   ============================================================
echo    ПРОЕКТ УСТАНОВЛЕН И РАБОТАЕТ
echo   ============================================================
echo.
echo    Веб-интерфейс:     http://localhost:8000/
echo    Документация API:  http://localhost:8000/docs
echo.
echo   Сейчас откроется страница в браузере...
start "" http://localhost:8000/
echo.
echo   Полезные команды (запускаются в этой папке, в окне cmd):
echo     остановить проект:  docker compose stop
echo     запустить снова:    docker compose start
echo     посмотреть логи:    docker compose logs -f app
echo     обновить каталог:   docker compose exec app python -m app.seed
echo.
echo   Запуск Telegram-бота (когда добавишь токен в .env):
echo     docker compose exec app python -m app.bot.bot
echo.
pause
endlocal
