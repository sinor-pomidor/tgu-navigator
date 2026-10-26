"""Скрипт загрузки стартового каталога возможностей в базу данных.

Читает ``seed/opportunities.json``, полностью очищает таблицу
``opportunities`` и загружает записи заново. Идемпотентен: повторный
запуск не дублирует данные (всегда ровно столько записей, сколько в JSON).

Запуск:
    python -m app.seed [путь_к_json]
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import init_db, session_scope
from app.models import Opportunity, OpportunityStatus, OpportunityType

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "opportunities.json"


def load_records(path: Path) -> list[dict[str, Any]]:
    """Читает и валидирует JSON-файл с записями каталога.

    Args:
        path: путь к файлу ``opportunities.json``.

    Returns:
        Список словарей с полями возможностей.

    Raises:
        FileNotFoundError: файл не найден.
        ValueError: нарушен формат данных.
    """
    if not path.exists():
        raise FileNotFoundError(f"Файл сид-каталога не найден: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Ожидался JSON-массив записей")

    valid_types = {t.value for t in OpportunityType}
    valid_statuses = {s.value for s in OpportunityStatus}

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Запись #{i} не является объектом")
        if not item.get("title"):
            raise ValueError(f"У записи #{i} пустое поле title")
        if not item.get("source_url"):
            raise ValueError(f"У записи «{item.get('title')}» пуст source_url")
        if item.get("type") not in valid_types:
            raise ValueError(f"Запись #{i}: недопустимый type={item.get('type')!r}")
        if item.get("status") not in valid_statuses:
            raise ValueError(f"Запись #{i}: недопустимый status={item.get('status')!r}")
        if not isinstance(item.get("tags", []), list):
            raise ValueError(f"Запись #{i}: tags должен быть списком строк")

    return raw


def build_opportunity(item: dict[str, Any]) -> Opportunity:
    """Преобразует словарь из JSON в ORM-объект ``Opportunity``."""
    deadline_value: date | None = None
    if item.get("deadline"):
        deadline_value = date.fromisoformat(str(item["deadline"]))

    return Opportunity(
        type=OpportunityType(item["type"]),
        title=item["title"].strip(),
        description=item.get("description"),
        requirements=item.get("requirements"),
        audience=item.get("audience"),
        tags=[str(tag) for tag in item.get("tags", [])],
        deadline=deadline_value,
        status=OpportunityStatus(item.get("status", OpportunityStatus.OPEN.value)),
        contact=item.get("contact"),
        source_url=item["source_url"].strip(),
    )


def seed_database(path: Path = DEFAULT_SEED_PATH) -> int:
    """Перезагружает каталог из JSON-файла в базу данных.

    Таблица предварительно очищается, поэтому повторные запуски
    не создают дублей.

    Args:
        path: путь к JSON-файлу с каталогом.

    Returns:
        Количество загруженных записей.
    """
    records = load_records(path)
    with session_scope() as session:
        # Полная перезагрузка: удаляем старые строки, вставляем новые.
        # delete() выполняется сразу в БД — так добавленные в этом же
        # транзакционном скоупе объекты не попадают под очистку.
        session.query(Opportunity).delete()

        for item in records:
            session.add(build_opportunity(item))

        total = len(records)
    logger.info("Каталог перезагружен из %s: %d записей", path, total)
    return total


def main() -> None:
    """Точка входа ``python -m app.seed``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED_PATH
    init_db()
    count = seed_database(path)
    logger.info("Готово: в базе %d возможностей", count)


if __name__ == "__main__":
    main()
