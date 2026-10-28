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
