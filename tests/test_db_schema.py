"""Тесты структурной формы базы данных (docs/DB_SCHEMA.md).

Проверяют, что модель Opportunity соответствует разделу 5 ТЗ: состав полей,
обязательность, имена индексов; а init_db() создаёт общие индексы и идемпотентен
при повторном развёртывании на существующей базе. База — изолированная
(tgu_test / временный SQLite), задаётся в conftest до импорта приложения.
"""

from __future__ import annotations

from app.db import get_engine, init_db
from app.models import Opportunity


def test_table_has_all_spec_columns() -> None:
    """Все 17 полей из раздела 5 ТЗ присутствуют в модели."""
    expected = {
        "id", "type", "title", "description", "requirements", "audience",
        "tags", "deadline", "status", "contact", "source_url", "source",
        "origin", "last_seen_at", "external_id", "created_at", "updated_at",
    }
    actual = {c.name for c in Opportunity.__table__.columns}
    assert expected == actual


def test_required_columns_not_nullable() -> None:
    """Обязательные поля каталога помечены NOT NULL, остальные — nullable."""
    cols = {c.name: c for c in Opportunity.__table__.columns}
    for name in ("type", "title", "source_url", "status", "origin", "tags"):
        assert not cols[name].nullable, f"{name} должен быть NOT NULL"
    for name in ("description", "requirements", "audience", "deadline",
                 "contact", "last_seen_at", "external_id"):
        assert cols[name].nullable, f"{name} должен быть nullable"


def test_declared_common_indexes_names() -> None:
    """Общие индексы (обе СУБД) объявлены с именами из docs/DB_SCHEMA.md."""
    names = {i.name for i in Opportunity.__table__.indexes}
    assert {
        "ix_opportunities_type_status",
        "ix_opportunities_source_url",
        "ix_opportunities_deadline",
    } <= names


def test_postgres_only_indexes_names() -> None:
    """Postgres-специфичные индексы соответствуют документации схемы."""
    names = {i.name for i in Opportunity.postgres_only_indexes()}
    assert names == {
        "ix_opportunities_title_trgm",
        "ix_opportunities_description_trgm",
        "ix_opportunities_tags_gin",
        "uq_opportunities_source_external",
    }


def _table_indexes(eng) -> set[str]:
    """Возвращает имена индексов таблицы opportunities для любой СУБД."""
    from sqlalchemy import inspect

    return {i["name"] for i in inspect(eng).get_indexes("opportunities")}


def test_init_db_creates_common_indexes_is_idempotent() -> None:
    """init_db создаёт таблицу и общие индексы; повторный вызов не падает.

    На SQLite инспектор отражает только обычные btree-индексы (роль GIN
    выполняет деградированный ILIKE-поиск), поэтому ожидаем три общих
    индекса; на PostgreSQL дополнительно проверяются trgm/GIN-индексы.
    """
    init_db(seed_if_empty=False)
    init_db(seed_if_empty=False)  # повторное развёртывание безопасно

    eng = get_engine()
    indexes = _table_indexes(eng)
    assert {
        "ix_opportunities_type_status",
        "ix_opportunities_source_url",
        "ix_opportunities_deadline",
    } <= indexes
    if eng.dialect.name != "sqlite":
        assert {
            "ix_opportunities_title_trgm",
            "ix_opportunities_description_trgm",
            "ix_opportunities_tags_gin",
        } <= indexes
