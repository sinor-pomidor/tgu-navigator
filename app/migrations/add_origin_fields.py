"""Идемпотентная миграция: поля origin / last_seen_at / external_id / source.

Проект на этапе прототипа не использует Alembic — схема разворачивается
через ``create_all``. Для уже существующей БД (например, демо-базы с
заполненным каталогом) этот скрипт добавляет недостающие колонки через
``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` и помечает все существующие
записи как ручные (``origin='manual'``).

Повторный запуск безопасен: ни одна операция не падает, если изменение
уже применено.

Запуск:
    python -m app.migrations.add_origin_fields
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db import get_engine, session_scope

logger = logging.getLogger(__name__)

#: Идемпотентные DDL/DML-операции миграции.
STATEMENTS: list[str] = [
    """
    ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'manual'
    """,
    """
    ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS external_id TEXT
    """,
    """
    ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual'
    """,
    # Существующие (в т.ч. seed-)записи — ручные данные кураторов.
    "UPDATE opportunities SET origin = 'manual' WHERE origin IS NULL",
    # Частичный уникальный индекс для дедупликации parsed-записей.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_source_external
        ON opportunities (source, external_id)
        WHERE origin = 'parsed' AND external_id IS NOT NULL
    """,
]


def migrate() -> None:
    """Применяет все DDL/DML-операции миграции к текущей базе."""
    engine = get_engine()
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
    logger.info("Миграция add_origin_fields применена (идемпотентно)")


def main() -> None:
    """Точка входа ``python -m app.migrations.add_origin_fields``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    migrate()
    with session_scope() as session:
        total = session.execute(
            text("SELECT count(*) FROM opportunities")
        ).scalar_one()
        manual = session.execute(
            text("SELECT count(*) FROM opportunities WHERE origin = 'manual'")
        ).scalar_one()
    logger.info(
        "Готово: записей в каталоге %d, из них origin='manual' — %d",
        total,
        manual,
    )


if __name__ == "__main__":
    main()
