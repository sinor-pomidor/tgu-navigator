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


class Opportunity(Base):
    """Запись каталога возможностей ТГУ."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    type: Mapped[OpportunityType] = mapped_column(
        Enum(OpportunityType, name="opportunity_type", native_enum=False),
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
        Enum(OpportunityStatus, name="opportunity_status", native_enum=False),
        nullable=False,
        default=OpportunityStatus.OPEN,
        server_default=OpportunityStatus.OPEN.value,
    )
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

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
    )

    def __repr__(self) -> str:  # pragma: no cover - служебное представление
        return f"<Opportunity id={self.id} type={self.type.value} title={self.title!r}>"
