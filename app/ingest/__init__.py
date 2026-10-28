"""Конвейер сбора данных (ingestion) для каталога возможностей.

Архитектура (см. ТЗ блока ingestion):

    Источник (Source) --> RawItem --> Валидация/нормализация --> Upsert-загрузчик --> БД

Новые источники (VK API, Telegram-каналы на этапе 2) добавляются как
классы-наследники ``BaseSource`` с методом ``fetch()`` — без изменения
конвейера и загрузчика.
"""

from app.ingest.base import BaseSource, RawItem, SourceRegistry
from app.ingest.loaders import IngestReport, upsert_items

__all__ = [
    "BaseSource",
    "RawItem",
    "SourceRegistry",
    "IngestReport",
    "upsert_items",
]
