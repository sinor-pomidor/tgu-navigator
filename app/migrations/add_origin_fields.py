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
from app.progress import progress_bar

logger = logging.getLogger(__name__)

#: Идемпотентные DDL/DML-операции миграции для PostgreSQL.
#: SQLite не поддерживает ``ADD COLUMN IF NOT EXISTS``, ``TIMESTAMPTZ`` и
#: частичные индексы — для него используется список ниже (проверка колонки
#: через PRAGMA table_info перед каждым ALTER).
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

#: Колонки, которые миграция добавляет (для проверки в SQLite).
_SQLITE_COLUMNS: dict[str, str] = {
    "origin": "TEXT NOT NULL DEFAULT 'manual'",
    "last_seen_at": "DATETIME",
    "external_id": "TEXT",
    "source": "TEXT NOT NULL DEFAULT 'manual'",
}

#: Уникальный индекс для дедупликации parsed-записей в SQLite.
#: Частичный индекс (WHERE) не поддерживается — уникальность по паре
#: (source, external_id) достаточна: у ручных записей external_id NULL,
#: а NULL в SQLite не участвует в проверке уникальности.
_SQLITE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_source_external
    ON opportunities (source, external_id)
"""


def _migrate_sqlite(conn) -> None:  # noqa: ANN001
    """Применяет миграцию к SQLite с проверкой существующих колонок."""
    existing = {
        row[1] for row in conn.execute(text("PRAGMA table_info(opportunities)"))
    }
    for column, ddl_type in _SQLITE_COLUMNS.items():
        if column not in existing:
            conn.execute(
                text(f"ALTER TABLE opportunities ADD COLUMN {column} {ddl_type}")
            )
    conn.execute(text("UPDATE opportunities SET origin = 'manual' WHERE origin IS NULL"))
    conn.execute(text(_SQLITE_INDEX))


def migrate() -> None:
    """Применяет все DDL/DML-операции миграции к текущей базе.

    Диалект определяется по строке подключения: для SQLite используются
    совместимые конструкции (PRAGMA + обычный ALTER), для PostgreSQL —
    исходный набор statements. Метод идемпотентен для обеих СУБД.
    """
    engine = get_engine()
    bar = progress_bar(len(STATEMENTS), "Миграция схемы")
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            _migrate_sqlite(conn)
            bar.update(len(STATEMENTS))
        else:
            for i, stmt in enumerate(STATEMENTS, start=1):
                conn.execute(text(stmt))
                bar.update(i)
    bar.finish()
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
