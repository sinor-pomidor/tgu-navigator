"""Реестр источников конвейера ingestion.

Реестр позволяет регистрировать источники по имени и запускать их выборочно
или все сразу — добавление нового источника не требует правок оркестратора.
Глобальный экземпляр ``registry`` наполняется в ``run.py``.
"""

from __future__ import annotations

import logging

from app.ingestion.base import BaseSource

logger = logging.getLogger(__name__)


class SourceRegistry:
    """Реестр источников: позволяет добавлять новые без правок конвейера."""

    def __init__(self) -> None:
        self._sources: dict[str, BaseSource] = {}

    def register(self, source: BaseSource) -> None:
        """Регистрирует экземпляр источника (перерегистрация перезаписывает)."""
        if not source.name:
            raise ValueError("У источника должно быть непустое имя (атрибут name)")
        self._sources[source.name] = source

    def get(self, name: str) -> BaseSource | None:
        """Возвращает источник по имени либо None."""
        return self._sources.get(name)

    def all(self) -> list[BaseSource]:
        """Список всех зарегистрированных источников (по алфавиту имён)."""
        return [self._sources[k] for k in sorted(self._sources)]


#: Глобальный реестр; конкретные источники регистрирует run.py.
registry = SourceRegistry()
