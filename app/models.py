"""SQLAlchemy-модели предметной области «ТГУ: Навигатор возможностей».

Единственная на этапе прототипа таблица — ``opportunities`` (каталог
проверенных университетских возможностей). Поля и типы соответствуют
разделу 5 технического задания.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, DATE
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


class OpportunityType(str, enum.Enum):
    """Тип возможности."""

    PROJECT = "project"
    LAB = "lab"
    EVENT = "event"
    GRANT = "grant"


class OpportunityStatus(str, enum.Enum):
    """Статус активности возможности."""

    OPEN = "open"
    CLOSING_SOON = "closing_soon"
    CLOSED = "closed"


class OpportunityOrigin(str, enum.Enum):
    """Источник происхождения записи каталога.

    ``manual`` — заведена человеком (seed, CRUD API, импорт куратора);
    ``parsed`` — собрана автоматическим конвейером ingestion.
    Ручные записи конвейер не перезаписывает и не удаляет.
    """

    MANUAL = "manual"
    PARSED = "parsed"


class Opportunity(Base):
    """Запись каталога возможностей ТГУ."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # values_callable: в БД храним значения enum ('open'), а не имена ('OPEN').
    type: Mapped[OpportunityType] = mapped_column(
        Enum(
            OpportunityType,
            name="opportunity_type",
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    deadline: Mapped[date | None] = mapped_column(DATE, nullable=True)
    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(
            OpportunityStatus,
            name="opportunity_status",
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=OpportunityStatus.OPEN,
        server_default=OpportunityStatus.OPEN.value,
    )
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )

    # Поля конвейера сбора данных (ingestion).
    origin: Mapped[OpportunityOrigin] = mapped_column(
        Enum(
            OpportunityOrigin,
            name="opportunity_origin",
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=OpportunityOrigin.MANUAL,
        server_default=OpportunityOrigin.MANUAL.value,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # GIN-индексы pg_trgm для полнотекстового поиска (Задача 5).
        # Создаются только если расширение pg_trgm доступно в БД;
        # при недоступности init_db логирует предупреждение и продолжает работу.
        Index(
            "ix_opportunities_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_opportunities_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        # GIN-индекс по массиву тегов.
        Index(
            "ix_opportunities_tags_gin",
            "tags",
            postgresql_using="gin",
        ),
        # Частичный уникальный индекс: external_id уникален в рамках
        # источника (source) только для записей, собранных конвейером.
        # Ручные записи (origin='manual') имеют external_id IS NULL и
        # под правило не попадают — дедупликация кураторских записей
        # остаётся на ответственности человека.
        Index(
            "uq_opportunities_source_external",
            "source",
            "external_id",
            unique=True,
            postgresql_where=text("origin = 'parsed' AND external_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - служебное представление
        return f"<Opportunity id={self.id} type={self.type.value} title={self.title!r}>"
