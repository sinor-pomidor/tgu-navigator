"""Интерфейс LLM-провайдера и фабрика выбора реализации (Задача 6).

Ключевое продуктовое правило: ответ ассистента опирается ТОЛЬКО на данные
каталога. Поэтому провайдер получает уже готовые результаты поиска и лишь
формулирует ответ — модель с нуля ничего не «знает» о возможностях ТГУ.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

from app.services.search import SearchResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnswerCard:
    """Карточка одной возможности в составе ответа."""

    id: int
    type: str
    title: str
    summary: str
    requirements: str | None
    deadline: str | None
    contact: str | None
    source_url: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Сериализация карточки в JSON-совместимый словарь."""
        return asdict(self)


@dataclass(frozen=True)
class Answer:
    """Структурированный ответ ассистента.

    * ``intro`` — текст-вступление (что нашли и почему);
    * ``cards`` — подборка карточек;
    * ``next_step`` — предложение следующего шага;
    * ``sources`` — ВСЕГДА список источников (название + официальная ссылка);
    * ``found`` — False, если подбор пуст (честный ответ «не найдено»).
    """

    intro: str
    cards: list[AnswerCard] = field(default_factory=list)
    next_step: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)
    found: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Полная сериализация ответа для JSON-API."""
        return {
            "intro": self.intro,
            "cards": [c.to_dict() for c in self.cards],
            "next_step": self.next_step,
            "sources": self.sources,
            "found": self.found,
        }


class LLMProvider(ABC):
    """Интерфейс провайдера, формулирующего ответ по результатам поиска."""

    @abstractmethod
    def compose_answer(self, query: str, results: list[SearchResult]) -> Answer:
        """Собрать структурированный ответ по запросу и выдаче поиска.

        Args:
            query: исходная фраза пользователя.
            results: релевантные возможности (может быть пустым).

        Returns:
            Готовый ``Answer``; при пустой выдаче — ответ с ``found=False``.
        """


def card_from_result(result: SearchResult) -> AnswerCard:
    """Сконвертировать запись поиска в карточку ответа (общая логика)."""
    opp = result.opportunity
    summary = (opp.description or "").strip() or opp.title
    if len(summary) > 280:
        summary = summary[:280].rstrip() + "…"
    type_value = opp.type.value if hasattr(opp.type, "value") else str(opp.type)
    status_value = (
        opp.status.value if hasattr(opp.status, "value") else str(opp.status)
    )
    return AnswerCard(
        id=opp.id,
        type=type_value,
        title=opp.title,
        summary=summary,
        requirements=(opp.requirements or None),
        deadline=opp.deadline.isoformat() if opp.deadline else None,
        contact=opp.contact,
        source_url=opp.source_url,
        status=status_value,
    )


def build_sources(cards: list[AnswerCard]) -> list[dict[str, str]]:
    """Список источников ответа: название + официальная ссылка (без дублей)."""
    seen: set[str] = set()
    sources: list[dict[str, str]] = []
    for card in cards:
        if card.source_url in seen:
            continue
        seen.add(card.source_url)
        sources.append({"title": card.title, "url": card.source_url})
    return sources


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    """Фабрика активного LLM-провайдера по настройке ``LLM_PROVIDER``.

    Значения: ``mock`` (по умолчанию, без сети и ключей) или
    ``openai_compatible`` (требует LLM_API_BASE/LLM_API_KEY/LLM_MODEL;
    при неполной конфигурации безопасно откатывается на mock).
    """
    from app.config import get_settings

    settings = get_settings()
    provider_name = (settings.llm_provider or "mock").strip().lower()

    if provider_name == "openai_compatible":
        if settings.llm_api_key and settings.llm_api_base and settings.llm_model:
            from app.services.llm.openai_compatible import (
                OpenAICompatibleProvider,
            )

            logger.info("Активирован OpenAI-совместимый LLM-провайдер")
            return OpenAICompatibleProvider(
                api_base=settings.llm_api_base,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
            )
        logger.warning(
            "LLM_PROVIDER=openai_compatible, но LLM_API_BASE/LLM_API_KEY/"
            "LLM_MODEL заданы не полностью — откат на mock-провайдер"
        )
    elif provider_name != "mock":
        logger.warning(
            "Неизвестный LLM_PROVIDER=%r — используем mock", provider_name
        )

    from app.services.llm.mock import MockProvider

    return MockProvider()
