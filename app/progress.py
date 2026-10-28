"""Текстовый прогресс-бар для консольных установщиков и запускаторов.

Модуль используется скриптами загрузки данных (``python -m app.seed``,
``python -m app.ingestion.csv_import``, ``python -m app.ingestion.run``),
которые вызываются из ``install.sh`` / ``install.bat`` / ``run.sh`` / ``run.bat``:
пока идёт долгая работа, пользователь видит честный процент вместо тишины.

Особенности:
  * вывод только в stderr — stdout остаётся чистым для pipe/перехвата;
  * если stderr не является терминалом (перенаправление в файл/CI),
    бар молча отключается и печатает лишь итоговую строку;
  * никаких внешних зависимостей (tqdm запрещён политикой стека).
"""

from __future__ import annotations

import shutil
from pathlib import Path
import sys
import time
from typing import TextIO


class ProgressBar:
    """Простой текстовый прогресс-бар вида ``[####----] 40% label``.

    Args:
        total: общее число шагов (должно быть >= 1).
        label: короткая подпись справа от бара (на русском).
        width: ширина бара в символах; по умолчанию подбирается под
            ширину терминала, чтобы строка не переносилась.
        stream: куда писать; по умолчанию ``sys.stderr``.
        enabled: принудительно включить/выключить; по умолчанию бар
            активен только для интерактивного терминала.
    """

    def __init__(
        self,
        total: int,
        label: str = "",
        *,
        width: int | None = None,
        stream: TextIO | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.total = max(1, int(total))
        self.label = label
        self.stream = stream if stream is not None else sys.stderr
        if enabled is None:
            enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.enabled = enabled
        self.width = width if width is not None else self._auto_width()
        self._start = time.monotonic()

    @staticmethod
    def _auto_width() -> int:
        """Подбирает ширину бара под терминал (8..30 символов)."""
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        return max(8, min(30, cols - 30))

    def _render(self, done: int, suffix: str = "") -> None:
        """Рисует одну строку состояния с carriage-return."""
        pct = min(done * 100 // self.total, 100)
        filled = pct * self.width // 100
        bar = "#" * filled + "-" * (self.width - filled)
        elapsed = int(time.monotonic() - self._start)
        text = f"\r    [{bar}] {pct:3d}%  {self.label} ({done}/{self.total}) {elapsed}s{suffix}"
        try:
            self.stream.write(text)
            self.stream.flush()
        except (ValueError, OSError):
            pass  # поток закрыт — просто не показываем прогресс

    def update(self, done: int) -> None:
        """Обновляет состояние до шага ``done`` (от 0 до ``total``)."""
        if self.enabled:
            self._render(max(0, min(done, self.total)))

    def finish(self) -> None:
        """Дорисовывает 100 % и переводит строку."""
        if self.enabled:
            full = "#" * self.width
            self.stream.write(
                f"\r    [{full}] 100%  {self.label} ({self.total}/{self.total})\n"
            )
            self.stream.flush()


def progress_bar(total: int, label: str = "", **kwargs: object) -> ProgressBar:
    """Создаёт :class:`ProgressBar` (функция-обёртка для читаемости вызовов)."""
    return ProgressBar(total, label, **kwargs)  # type: ignore[arg-type]


def run_with_progress(
    cmd: list[str],
    total: int,
    label: str,
    *,
    timeout: float | None = None,
) -> int:
    """Запускает дочерний процесс и показывает честный прогресс-бар.

    Ориентир прогресса — число файлов в ``data/`` (SQLite-база): каждый
    шаг долгих операций (миграция схемы, загрузка каталога) изменяет файл
    базы, поэтому бар реально отражает ход работы. Если ориентир недоступен,
    бар деградирует до анимации по времени.

    Args:
        cmd: команда запуска дочернего процесса (например ``[sys.executable, "-m", "app.seed"]``).
        total: ожидаемое общее число «шагов» для процента.
        label: подпись бара на русском.
        timeout: максимальное время ожидания в секундах; по умолчанию без лимита.

    Returns:
        Код завершения дочернего процесса (124 — таймаут, 127 — процесс не найден).
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    try:
        from app.config import LOCAL_SQLITE_PATH as _DB_PATH

        db_path = Path(_DB_PATH)
    except Exception:  # pragma: no cover - конфиг может не импортироваться вне venv
        db_path = root / "data" / "navigator.db"
    bar = ProgressBar(total, label)
    try:
        proc = subprocess.Popen(cmd)
    except OSError as exc:
        print(f"    [ОШИБКА] не удалось запустить {cmd[0]}: {exc}", file=sys.stderr)
        return 127
    step = 0
    last_mtime: float = -1.0
    if db_path.exists():
        last_mtime = db_path.stat().st_mtime
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while True:
            rc_now = proc.poll()
            done = step
            if db_path.exists():
                mtime = db_path.stat().st_mtime
                if mtime > last_mtime:
                    last_mtime = mtime
                    step += 1
            bar.update(min(done, total))
            if rc_now is not None:
                break
            if deadline is not None and time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                print(
                    f"\n    [ОШИБКА] работа превысила {int(timeout or 0)} c и прервана.",
                    file=sys.stderr,
                )
                return 124
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                continue
        rc = proc.returncode if proc.returncode is not None else 0
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        print("\n    [ПРЕРВАНО] работа остановлена пользователем.", file=sys.stderr)
        return 130
    bar.update(total)
    bar.finish()
    return rc


def _main(argv: list[str] | None = None) -> int:
    """CLI-точка входа ``python -m app.progress``.

    Использование::

        python -m app.progress --total 5 --label "Миграция" -- python -m app.migrations.add_origin_fields
        python -m app.progress --total 20 --label "Каталог"   -- python -m app.seed
    """
    import argparse

    parser = argparse.ArgumentParser(prog="app.progress")
    parser.add_argument("--total", type=int, default=1)
    parser.add_argument("--label", default="Работа")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)
    cmd = list(ns.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("Нет команды после '--'.", file=sys.stderr)
        return 2
    return run_with_progress(cmd, ns.total, ns.label, timeout=ns.timeout)


if __name__ == "__main__":
    sys.exit(_main())
