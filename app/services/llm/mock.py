"""Mock-провайдер: детерминированная сборка ответа без сети и ключей.

Используется по умолчанию (LLM_PROVIDER=mock). Ответ формируется строго
по данным из результатов поиска: шаблонное вступление, карточки возможностей
и предложение следующего шага. Никаких обращений к внешним API — прототип
полностью работоспособен офлайн. Если результатов нет — честный ответ
«не найдено» с рекомендацией переформулировать запрос.
"""

from __future__ import annotations

import logging

from app.services.llm.base import (
    Answer,
    LLMProvider,
    build_sources,
    card_from_result,
)
from app.services.search import SearchResult

logger = logging.getLogger(__name__)

#: Человекочитаемые названия типов для текста ответа.
_TYPE_LABELS: dict[str, str] = {
    "project": "проект",
    "lab": "лаборатория",
    "event": "мероприятие",
    "grant": "грант",
}

_NOT_FOUND_INTRO = (
    "К сожалению, по вашему запросу ничего подходящего в каталоге "
    "возможностей ТГУ не нашлось."
)
_NOT_FOUND_NEXT_STEP = (
    "Попробуйте переформулировать запрос: укажите тему или направление "
    "(например, «искусственный интеллект», «NLP», «стартапы»), тип "
    "возможности («проект», «лаборатория», «грант», «мероприятие») или "
    "ваш факультет. Можно также комбинировать: «грант для магистрантов "
    "по биотехнологиям»."
)


class MockProvider(LLMProvider):
    """Провайдер-заглушка: собирает ответ по шаблонам из данных каталога."""

    def compose_answer(
        self, query: str, results: list[SearchResult]
    ) -> Answer:
        """Сформировать детерминированный ответ по результатам поиска.

        Args:
            query: исходная фраза пользователя (влияет только на текст).
            results: выдача гибридного поиска (может быть пустой).

        Returns:
            ``Answer`` с вступлением, карточками, следующим шагом и
            обязательным списком источников. При пустой выдаче —
            ``found=False`` и подсказка о переформулировании.
        """
        if not results:
            logger.info("Mock-провайдер: результатов нет, отвечаем «не найдено»")
            return Answer(
                intro=_NOT_FOUND_INTRO,
                cards=[],
                next_step=_NOT_FOUND_NEXT_STEP,
                sources=[],
                found=False,
            )

        cards = [card_from_result(r) for r in results]

        # Типы найденного — для вступления («2 проекта и 1 лаборатория»).
        label_counts: dict[str, int] = {}
        for card in cards:
            label = _TYPE_LABELS.get(card.type, card.type)
            label_counts[label] = label_counts.get(label, 0) + 1
        mix = ", ".join(
            f"{count} {_plural(label, count)}"
            for label, count in sorted(
                label_counts.items(), key=lambda kv: -kv[1]
            )
        )

        intro = (
            f"По запросу «{query.strip()}» нашёл в каталоге ТГУ {len(cards)} "
            f"подходящих возможностей: {mix}. Все подборки основаны на "
            "проверенных данных университета — подробности и актуальные "
            "условия смотрите по официальным ссылкам."
        )

        first = cards[0]
        if first.contact:
            next_step = (
                f"Советую начать с «{first.title}»: свяжитесь с куратором "
                f"({first.contact}) или откройте источник по кнопке "
                "«Подробнее». Если ни одна карточка не подошла — уточните "
                "тему или фильтр (тип, срок)."
            )
        else:
            next_step = (
                f"Советую начать с «{first.title}» — откройте официальный "
                "источник по кнопке «Подробнее». Если ни одна карточка не "
                "подошла — уточните тему или тип возможности."
            )

        return Answer(
            intro=intro,
            cards=cards,
            next_step=next_step,
            sources=build_sources(cards),
            found=True,
        )


def _plural(label: str, count: int) -> str:
    """Простейшее склонение существительного по числу (для метки типа)."""
    forms = {
        "проект": ("проект", "проекта", "проектов"),
        "лаборатория": ("лаборатория", "лаборатории", "лабораторий"),
        "мероприятие": ("мероприятие", "мероприятия", "мероприятий"),
        "грант": ("грант", "гранта", "грантов"),
    }
    trio = forms.get(label)
    if not trio:
        return label if count == 1 else f"{label}s"
    n = abs(count) % 100
    n1 = n % 10
    if n > 10 and n < 20:
        return trio[2]
    if n1 == 1:
        return trio[0]
    if n1 in (2, 3, 4):
        return trio[1]
    return trio[2]
