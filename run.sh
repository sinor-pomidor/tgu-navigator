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
    echo "  Устанавливаем пакеты, это займёт пару минут. Ниже — прогресс:"
    python -m pip install --upgrade pip
    pip install -r requirements.txt && touch .venv/.tgu-deps-ok
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
for i in $(seq 1 20); do
    if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

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
