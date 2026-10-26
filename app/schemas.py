"""Pydantic-схемы запросов и ответов API каталога возможностей.

Схемы разделяются на три группы: создающие (Create), обновляющие (Update,
все поля опциональны) и отвечающие (Response, с служебными полями id и
таймстампами). Строковые поля нормализуются по пробелам, пустые строки
в необязательных полях превращаются в None.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import OpportunityStatus, OpportunityType


class OpportunityBase(BaseModel):
    """Общие поля создания/ответа записи каталога."""

    type: OpportunityType
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    requirements: str | None = None
    audience: str | None = None
    tags: list[str] = Field(default_factory=list)
    deadline: date | None = None
    status: OpportunityStatus = OpportunityStatus.OPEN
    contact: str | None = None
    source_url: str = Field(min_length=1, max_length=1000)

    @field_validator("title", "source_url")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        """Обрезает пробелы; обязательное поле не может стать пустым."""
        value = value.strip()
        if not value:
            raise ValueError("поле не может быть пустым")
        return value

    @field_validator("description", "requirements", "audience", "contact")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        """Пустые строки в необязательных полях нормализует в None."""
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        """Убирает пустые теги, дубликаты (без учёта регистра), пробелы."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for tag in value:
            tag = tag.strip()
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(tag)
        return cleaned


class OpportunityCreate(OpportunityBase):
    """Схема тела POST /opportunities."""


class OpportunityUpdate(BaseModel):
    """Схема тела PUT /opportunities/{id} — все поля опциональны."""

    type: OpportunityType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    requirements: str | None = None
    audience: str | None = None
    tags: list[str] | None = None
    deadline: date | None = None
    status: OpportunityStatus | None = None
    contact: str | None = None
    source_url: str | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("title", "source_url")
    @classmethod
    def _strip_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("поле не может быть пустым")
        return value

    @field_validator("description", "requirements", "audience", "contact")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for tag in value:
            tag = tag.strip()
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(tag)
        return cleaned


class Opportunity(OpportunityBase):
    """Схема ответа API: запись каталога целиком."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
