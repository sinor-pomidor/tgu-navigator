#!/usr/bin/env bash
# ============================================================================
#  ТГУ: Навигатор возможностей — установка и запуск (Linux / macOS)
#  Просто запусти этот файл в терминале:  ./install.sh
#  Скрипт ничего не ломает: он проверяет Docker, создаёт конфиг,
#  собирает контейнеры, загружает каталог возможностей и открывает проверку.
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[1;32m✔ %s\033[0m\n' "$1"; }
warn() { printf '    \033[1;33m⚠ %s\033[0m\n' "$1"; }
fail() { printf '    \033[1;31m✘ %s\033[0m\n' "$1"; exit 1; }


# ---------------------------------------------------------------------------
# bar_wait_until <PID> <max_sec> <label> - анимированный прогресс-бар,
# пока фоновый процесс с указанным PID живёт.
# ---------------------------------------------------------------------------
bar_wait_until() {
    local pid="$1" max="$2" label="${3:-Работа}"
    local n=0 width=30
    while kill -0 "$pid" 2>/dev/null && [ "$n" -lt "$max" ]; do
        local pct=$(( n * 100 / max ))
        [ "$pct" -gt 97 ] && pct=97
        local filled=$(( pct * width / 100 ))
        local bar=""
        for ((i=0;i<width;i++)); do
            if [ "$i" -lt "$filled" ]; then bar="${bar}#"; else bar="${bar}-"; fi
        done
        printf "\r    [%s] %3d%%  %s (%ds)" "$bar" "$pct" "$label" "$n"
        sleep 1
        n=$(( n + 1 ))
    done
    # финальная отрисовка 100%
    local full_bar=""
    for ((i=0;i<width;i++)); do full_bar="${full_bar}#"; done
    printf "\r    [%s] 100%%  %s\n" "$full_bar" "$label"
}

# ----------------------------------------------------------------------------
# Шаг 1. Проверяем, что Docker установлен и запущен
# ----------------------------------------------------------------------------
say "Шаг 1/5: проверка Docker"
if ! command -v docker >/dev/null 2>&1; then
    fail "Docker не найден. Установи Docker Desktop: https://www.docker.com/products/docker-desktop/ и повтори запуск скрипта."
fi
if ! docker info >/dev/null 2>&1; then
    fail "Docker установлен, но НЕ запущен. Открой приложение Docker Desktop (дождись зелёного статуса) и повтори запуск скрипта."
fi
ok "Docker работает ($(docker --version))"

# ----------------------------------------------------------------------------
# Шаг 2. Создаём конфигурационный файл .env из образца (если его нет)
# ----------------------------------------------------------------------------
say "Шаг 2/5: конфигурация (.env)"
if [ -f .env ]; then
    ok ".env уже существует — оставляю как есть"
else
    cp .env.example .env
    # Для docker-compose контейнер app обязан получать DATABASE_URL Postgres:
    # без него приложение попытается открыть SQLite-файл, которого в образе нет.
    if command -v sed >/dev/null 2>&1; then
        sed -i.bak 's|^DATABASE_URL=$|DATABASE_URL=postgresql+psycopg2://navigator:navigator@db:5432/navigator|' .env && rm -f .env.bak
    fi
    ok "Создан .env из образца (DATABASE_URL для Docker прописан). Всё работает БЕЗ ключей (LLM_PROVIDER=mock)."
    warn "Если позже захочешь Telegram-бота или реальный ИИ — допиши токены в файл .env (открывается любым текстовым редактором)."
fi

# ----------------------------------------------------------------------------
# Шаг 3. Останавливаем старые контейнеры (если они были), собираем новые
# ----------------------------------------------------------------------------
say "Шаг 3/5: сборка и запуск контейнеров (база данных + сайт)"
echo "    Первый запуск скачивает образы — это может занять несколько минут."
docker compose down --remove-orphans >/dev/null 2>&1 || true
rm -f .dc-code.tmp
( docker compose up --build -d > .dc-build.log 2>&1; echo $? > .dc-code.tmp ) &
DC_PID=$!
bar_wait_until "$DC_PID" 600 "Сборка контейнеров"
wait "$DC_PID" 2>/dev/null || true
DC_CODE=$(cat .dc-code.tmp 2>/dev/null || echo 1)
rm -f .dc-code.tmp
if [ "$DC_CODE" != "0" ]; then
    echo "    Последние строки вывода сборки:"
    tail -n 20 .dc-build.log || true
    fail "Контейнеры не запустились. См. текст выше."
fi
ok "Контейнеры запущены"

# ----------------------------------------------------------------------------
# Шаг 4. Ждём готовности API и загружаем каталог возможностей
# ----------------------------------------------------------------------------
say "Шаг 4/5: ожидание запуска и загрузка каталога"
# Ждём подъёма API в фоновом цикле, а на переднем плане рисуем прогресс-бар.
(
    for i in $(seq 1 60); do
        curl -sf http://localhost:8000/health >/dev/null 2>&1 && exit 0
        sleep 2
    done
    exit 1
) &
API_PID=$!
bar_wait_until "$API_PID" 130 "Ожидание сайта (макс ~120 c)"
wait "$API_PID" 2>/dev/null && API_OK=1 || API_OK=0
if [ "$API_OK" != "1" ]; then
    echo "    Последние строки лога приложения:"
    docker compose logs app --tail 20
    fail "Сайт не поднялся за 2 минуты. См. лог выше."
fi
ok "API отвечает: /health → {"status":"ok"}"

say "Загрузка каталога возможностей (с прогресс-баром)"
rm -f .seed-code.tmp
( docker compose exec -T app python -m app.seed > .seed.log 2>&1; echo $? > .seed-code.tmp ) &
SEED_PID=$!
bar_wait_until "$SEED_PID" 180 "Загрузка каталога"
wait "$SEED_PID" 2>/dev/null || true
SEED_CODE=$(cat .seed-code.tmp 2>/dev/null || echo 1)
rm -f .seed-code.tmp
if [ "$SEED_CODE" != "0" ]; then
    echo "    Последние строки вывода:"
    tail -n 15 .seed.log 2>/dev/null || true
    fail "Не удалось загрузить каталог возможностей."
fi
ok "Каталог возможностей загружен в базу"

# ----------------------------------------------------------------------------
# Шаг 5. Итоговая проверка и подсказка
# ----------------------------------------------------------------------------
say "Шаг 5/5: проверка"
COUNT=$(curl -s "http://localhost:8000/opportunities" | grep -o '"id"' | wc -l | tr -d ' ')
ok "В каталоге ${COUNT} возможностей"

echo ""
printf '\033[1;32m🎉 ГОТОВО! Проект установлен и работает.\033[0m\n'
echo ""
echo "  🌐 Веб-интерфейс:      http://localhost:8000/"
echo "  📖 Документация API:   http://localhost:8000/docs"
echo ""
echo "  Полезные команды (в этой папке):"
echo "    остановить проект:   docker compose stop"
echo "    запустить снова:     docker compose start"
echo "    посмотреть логи:     docker compose logs -f app"
echo "    обновить каталог:    docker compose exec app python -m app.seed"
echo ""
echo "  Запустить Telegram-бота (когда добавишь токен в .env):"
echo "    docker compose exec app python -m app.bot.bot"
echo ""
