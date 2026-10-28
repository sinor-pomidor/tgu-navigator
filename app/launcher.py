"""Точка входа .exe-сборки «ТГУ: Навигатор возможностей».

Собирается PyInstaller (см. build-exe.yml в GitHub Actions): один файл
``TGU-Navigator.exe``, который пользователь запускает двойным щелчком —
без Python, без Docker, без установки.

Что делает при запуске:
1. Определяет каталог рядом с exe (в onefile-режиме ``__file__`` ведёт во
   временную папку распаковки, поэтому ориентируемся на ``sys.executable``).
2. Ставит рабочую директорию туда же — база ``data/navigator.db`` и ``.env``
   живут рядом с exe и переживают обновление программы.
3. Поднимает сервер uvicorn на 127.0.0.1:8000 в фоновом потоке.
4. Ждёт готовности ``/health`` и открывает браузер на http://localhost:8000.
5. Держит окно консоли открытым; закрытие окна останавливает сервер.

Запуск для разработки (без сборки): ``python -m app.launcher``.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

logger = logging.getLogger("app.launcher")

HOST = "127.0.0.1"
PORT = 8000


def _reconfigure_console() -> None:
    """Переключает консоль Windows в UTF-8.

    Без этого ``print`` русских строк и псевдографики падает с
    ``UnicodeEncodeError`` ('charmap' codec), когда stdout перенаправлен
    в файл (cp1251/cp866 вместо OEM-кодировки консоли). Вызывается до
    первого вывода; ошибки на не-Windows игнорируются.
    """
    if os.name == "nt":
        try:
            os.system("chcp 65001 >nul 2>&1")
        except Exception:  # noqa: BLE001 - не критично
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - stream может быть подменён
            pass


def bundle_dir() -> Path:
    """Каталог, в котором лежит exe (или репозиторий при запуске из исходников)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def wait_for_server(timeout_sec: float = 60.0) -> bool:
    """Опрашивает порт сервера до его готовности.

    Args:
        timeout_sec: максимальное время ожидания в секундах.

    Returns:
        ``True``, если сервер начал принимать соединения.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def run_server() -> None:
    """Запускает uvicorn в текущем потоке (вызывается из фонового потока)."""
    import uvicorn

    from app.main import app

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        # reload недопустим в собранном exe (нет watchfiles-источников)
        reload=False,
    )
    server = uvicorn.Server(config)
    server.run()


def main() -> int:
    """Основной поток launcher'а: окружение, сервер, браузер, цикл ожидания."""
    _reconfigure_console()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    root = bundle_dir()
    os.chdir(root)
    # Маркер exe-режима: включает самовосстановление базы в lifespan приложения.
    os.environ.setdefault("TGU_BUNDLE", "1")

    print("=" * 60)
    print("  ТГУ: Навигатор возможностей — локальный сервер")
    print("=" * 60)
    print(f"  Каталог данных : {root}")
    print(f"  Адрес в браузере: http://localhost:{PORT}")
    print("  Закрытие этого окна остановит сервер.")
    print("-" * 60)
    print("  Идёт запуск, подождите несколько секунд...")

    server_thread = threading.Thread(target=run_server, name="uvicorn", daemon=True)
    server_thread.start()

    if wait_for_server():
        print(f"  [OK] Сервер готов, открываю браузер: http://localhost:{PORT}/")
        try:
            webbrowser.open(f"http://localhost:{PORT}/")
        except Exception:  # noqa: BLE001 - отсутствие браузера не критично
            logger.warning("Не удалось открыть браузер автоматически.")
    else:
        print("  [WARN] Сервер не ответил за 60 секунд.")
        print("         Откройте http://localhost:%d вручную или перезапустите exe." % PORT)

    # Держим процесс живым, пока работает серверный поток.
    try:
        while server_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("  Остановка сервера...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
