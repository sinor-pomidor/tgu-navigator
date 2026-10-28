"""Пакет конвейера сбора данных (ingestion) — структура по ТЗ, раздел 4.

    Источник (BaseSource.fetch) --> RawItem --> нормализация/валидация
    (normalize) --> upsert-загрузчик --> БД

Модули пакета:

* ``base``        — контракт источника и «сырая» запись ``RawItem``;
* ``registry``    — реестр источников (расширение без правок конвейера);
* ``tsu_site``    — парсер публичных страниц сайта ТГУ;
* ``csv_import``  — CSV-импорт мероприятий для кураторов (задача I5);
* ``normalize``   — нормализация, валидация, upsert, статусы, hygiene;
* ``run``         — CLI оркестратор прогона всех источников.
"""

from __future__ import annotations

from app.ingestion.base import BaseSource, RawItem
from app.ingestion.normalize import IngestReport, upsert_items
from app.ingestion.registry import SourceRegistry, registry

__all__ = [
    "BaseSource",
    "RawItem",
    "SourceRegistry",
    "registry",
    "IngestReport",
    "upsert_items",
]
