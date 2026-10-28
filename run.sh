#!/usr/bin/env bash
# ============================================================================
#  ТГУ: Навигатор возможностей — запуск БЕЗ Docker (macOS / Linux)
#  Запуск: ./run.sh   (или: bash run.sh)
#  Остановка сервера: ./run.sh stop
#  Скрипт проверит Python, создаст изолированное окружение, установит
#  зависимости, запустит сервер и откроет браузер на http://localhost:8000
# ============================================================================
set -e
cd "$(dirname "$0")"

PID_FILE="server.pid"

# ---------------------------------------------------------------------------
# Режим остановки: ./run.sh stop
# ---------------------------------------------------------------------------
if [ "${1:-}" = "stop" ]; then
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "Сервер остановлен."
    else
        pkill -f "uvicorn app.main:app" 2>/dev/null || true
        echo "Сервер остановлен (по имени процесса)."
    fi
    exit 0
fi

echo
echo "============================================================"
echo "  ТГУ: Навигатор возможностей — простой запуск (без Docker)"
echo "============================================================"


# ---------------------------------------------------------------------------
# pkg_progress <venv_dir> <marker> <label> - показывает прогресс-бар, пока
# pip устанавливает пакеты; ориентир — число папок в site-packages.
# ---------------------------------------------------------------------------
pkg_progress() {
    local sitedir="$1" marker="$2" label="${3:-Установка пакетов}"
    local max=45 n=0 width=30
    while [ ! -f "$marker" ] && [ "$n" -lt 360 ]; do
        local count=0
        if [ -d "$sitedir" ]; then
            count=$(find "$sitedir" -maxdepth 1 -type d | wc -l)
            count=$(( count - 1 ))
        fi
        local pct=$(( count * 100 / max ))
        [ "$pct" -gt 97 ] && pct=97
        local filled=$(( pct * width / 100 ))
        local bar=""
        for ((i=0;i<width;i++)); do
            if [ "$i" -lt "$filled" ]; then bar="${bar}#"; else bar="${bar}-"; fi
        done
        printf "\r    [%s] %3d%%  %s (%d пакетов)" "$bar" "$pct" "$label" "$count"
        sleep 2
        n=$(( n + 2 ))
    done
    local full_bar=""
    for ((i=0;i<width;i++)); do full_bar="${full_bar}#"; done
    printf "\r    [%s] 100%%  %s\n" "$full_bar" "$label"
}

# ---------------------------------------------------------------------------
# bar_wait_until <PID> <max_sec> <label> - анимированный прогресс-бар,
# пока фоновый процесс с указанным PID живёт (или пока не истечёт max_sec).
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
    local full_bar=""
    for ((i=0;i<width;i++)); do full_bar="${full_bar}#"; done
    printf "\r    [%s] 100%%  %s\n" "$full_bar" "$label"
}

# ---------------------------------------------------------------------------
# Шаг 1. Ищем Python 3.9+
# ---------------------------------------------------------------------------
echo
echo "[Шаг 1/4] Проверка Python..."
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            PY="$cand"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    echo "  [ОШИБКА] Python 3.9+ не найден."
    echo "  macOS:  установи с https://www.python.org/downloads/ (пакет .pkg)"
    echo "  Ubuntu: sudo apt install python3-venv python3-pip"
    exit 1
fi
"$PY" --version
echo "  [OK] Python найден."

# ---------------------------------------------------------------------------
# Шаг 2. Виртуальное окружение + зависимости (первый запуск ~2-3 минуты)
# ---------------------------------------------------------------------------
echo
echo "[Шаг 2/4] Подготовка окружения..."
if [ ! -d ".venv" ]; then
    "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [ ! -f ".venv/.tgu-deps-ok" ]; then
    echo "  Устанавливаем пакеты, это займёт пару минут. Прогресс ниже:"
    rm -f .pip-done.tmp
    python -m pip install --upgrade pip >/dev/null 2>&1 || true
    # Реальный путь site-packages текущего venv (Python бывает 3.9/3.10/3.11/3.12+).
    SITE_DIR="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])' 2>/dev/null || echo "")"
    [ -z "$SITE_DIR" ] && SITE_DIR=".venv/lib/python3.11/site-packages"
    ( pip install -r requirements.txt > .pip-install.log 2>&1 && touch .venv/.tgu-deps-ok; touch .pip-done.tmp ) &
    PK_PID=$!
    pkg_progress "$SITE_DIR" ".pip-done.tmp" "Установка пакетов"
    wait "$PK_PID" 2>/dev/null || true
    if [ ! -f ".venv/.tgu-deps-ok" ]; then
        echo "    Последние строки вывода pip:"
        tail -n 15 .pip-install.log || true
        echo "    [ОШИБКА] Не удалось установить зависимости. Проверь интернет и запусти снова."
        exit 1
    fi
    rm -f .pip-done.tmp .pip-install.log
else
    echo "  Пакеты уже установлены - пропускаем."
fi
echo "  [OK] Окружение готово."

# ---------------------------------------------------------------------------
# Шаг 3. Запускаем сервер в фоне
# ---------------------------------------------------------------------------
echo
echo "[Шаг 3/4] Запуск сервера..."
nohup python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
echo "  [OK] Сервер запущен (PID $SERVER_PID, логи в server.log)."

# ---------------------------------------------------------------------------
# Шаг 4. Ждём готовности и открываем браузер
# ---------------------------------------------------------------------------
echo
echo "[Шаг 4/4] Ожидание запуска..."
api_up() {
    for _ in $(seq 1 20); do
        curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
}
api_up &
API_PID=$!
bar_wait_until "$API_PID" 25 "Подъём сервера"
wait "$API_PID" 2>/dev/null || true

if command -v open >/dev/null 2>&1; then
    open http://localhost:8000/          # macOS
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:8000/      # Linux
else
    echo "  Открой в браузере вручную: http://localhost:8000/"
fi

echo
echo "============================================================"
echo "  ГОТОВО! Адрес: http://localhost:8000"
echo
echo "  Как пользоваться:"
echo "    - пиши в поле внизу вопрос про проекты/гранты/мероприятия ТГУ"
echo
echo "  Чтобы ВЫКЛЮЧИТЬ проект:  ./run.sh stop   (или kill $SERVER_PID)"
echo "  Чтобы включить снова:    ./run.sh"
echo "  Логи сервера:            cat server.log"
echo "============================================================"
echo
echo "Не закрывай это окно терминала, пока работаешь с навигатором."
echo "(Сервер живёт в фоне; окно можно закрыть, но stop-команда ниже надёжнее.)"
