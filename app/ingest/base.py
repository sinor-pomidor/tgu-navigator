"""Интерфейс источника данных и реестр источников конвейера.

Любой источник (страница сайта ТГУ, CSV куратора, в будущем — VK API или
Telegram-канал) реализует ``BaseSource.fetch()``, возвращающий список
``RawItem`` — «сырых» записей до валидации. Конвейер работает только с
этим контрактом, поэтому добавление нового источника не требует правок
загрузчика и хранилища.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class RawItem:
    """Запись, извлечённая источником, до нормализации и валидации.

    Поля соответствуют модели ``Opportunity``; строки могут содержать
    «грязные» значения (лишние пробелы, пустые теги) — их исправляет
    нормализатор в загрузчике.
    """

    title: str
    source_url: str
    external_id: str | None = None
    type: str = "event"
    description: str | None = None
    requirements: str | None = None
    audience: str | None = None
    tags: list[str] = field(default_factory=list)
    deadline: date | None = None
    contact: str | None = None
    #: Имя источника («tsu_site», «csv_import» …) — попадает в колонку source.
    source_name: str = ""
    #: Произвольные данные источника для отладки (не сохраняются в БД).
    meta: dict[str, Any] = field(default_factory=dict)


class BaseSource(abc.ABC):
    """Контракт источника данных конвейера ingestion."""

    #: Уникальное имя источника; используется как value колонки ``source``
    #: и для дедупликации по паре (source, external_id).
    name: str = "base"

    @abc.abstractmethod
    def fetch(self) -> list[RawItem]:
        """Извлекает актуальный список записей из источника.

        Returns:
            Список «сырых» записей; пустой список допустим.

        Raises:
            Источник может бросать сетевые исключения — конвейер
            перехватывает их и фиксирует как ошибку забора.
        """

    def describe(self) -> str:
        """Человекочитаемое описание источника для логов."""
        return f"{self.name}: {type(self).__name__}"


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
