"""OpenAI-совместимый LLM-провайдер (Задача 6).

Работает с любым API, совместимым с ``POST {api_base}/chat/completions``
(OpenAI, YandexGPT, локальные vLLM/llama.cpp-серверы и т.д.) через httpx.
Активируется только когда в .env заданы LLM_PROVIDER=openai_compatible
и полный набор LLM_API_BASE / LLM_API_KEY / LLM_MODEL (см. base.get_provider).

Промпт содержит ЖЁСТКОЕ правило: модель может использовать ТОЛЬКО
переданные факты из каталога, ничего не выдумывать и обязательно указывать
ссылки-источники. Структура ответа (карточки, источники) всё равно
формируется из данных поиска — LLM пишет только текст-вступление и
следующий шаг, поэтому галлюцинации не попадают в карточки.

При любой сетевой ошибке или ошибке API провайдер безопасно откатывается
на детерминированный MockProvider — сервис остаётся работоспособным.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.services.llm.base import (
    Answer,
    LLMProvider,
    build_sources,
    card_from_result,
)
from app.services.llm.mock import MockProvider
from app.services.search import SearchResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ты — ассистент «ТГУ: Навигатор возможностей» для студентов Томского "
    "государственного университета. Тебе дан запрос студента и список "
    "найденных возможностей (JSON). Правила, которые нельзя нарушать:\n"
    "1. Используй ТОЛЬКО факты из переданного списка. Запрещено добавлять "
    "или выдумывать проекты, лаборатории, мероприятия, гранты, сроки, "
    "контакты, ссылки.\n"
    "2. Если список пуст — честно скажи, что ничего не найдено, и предложи "
    "переформулировать запрос (тема, тип возможности, направление).\n"
    "3. Упоминай официальные ссылки на источники для названных возможностей.\n"
    "4. Пиши на русском языке, дружелюбно и по делу, без markdown-разметки.\n"
    "Ответь СТРОГО JSON вида: "
    '{"intro": "текст-вступление (1-3 предложения)", '
    '"next_step": "предложение следующего шага (1-2 предложения)"}'
)

_TIMEOUT_SECONDS = 30.0


class OpenAICompatibleProvider(LLMProvider):
    """Провайдер через chat-completions API, совместимый с OpenAI."""

    def __init__(self, api_base: str, api_key: str, model: str) -> None:
        """Сохранить параметры подключения (без логирования ключа!)."""
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._fallback = MockProvider()

    def compose_answer(
        self, query: str, results: list[SearchResult]
    ) -> Answer:
        """Собрать ответ: карточки — из данных поиска, тексты — от LLM.

        Структурированные данные (карточки, источники) формируются строго
        из результатов поиска. LLM формулирует только вступление и
        следующий шаг; при сетевых сбоях используется mock-шаблон.
        """
        cards = [card_from_result(r) for r in results]
        sources = build_sources(cards)

        if not results:
            # Пустая выдача — честный «не найдено» без обращения к сети.
            return self._fallback.compose_answer(query, results)

        llm_texts = self._request_texts(query, cards)
        if llm_texts is None:
            return self._fallback.compose_answer(query, results)

        intro, next_step = llm_texts
        return Answer(
            intro=intro,
            cards=cards,
            next_step=next_step,
            sources=sources,
            found=True,
        )

    def _request_texts(
        self, query: str, cards: list
    ) -> tuple[str, str] | None:
        """Один вызов chat/completions; None — при любой ошибке (откат)."""
        facts = [
            {
                "title": c.title,
                "type": c.type,
                "summary": c.summary,
                "requirements": c.requirements,
                "deadline": c.deadline,
                "contact": c.contact,
                "source_url": c.source_url,
            }
            for c in cards
        ]
        user_prompt = (
            f"Запрос студента: {query}\n\n"
            f"Найденные возможности (JSON): "
            f"{json.dumps(facts, ensure_ascii=False)}"
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        url = f"{self._api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(url, json=payload, headers=headers,
                                  timeout=_TIMEOUT_SECONDS)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(_strip_code_fence(content))
            intro = str(parsed.get("intro", "")).strip()
            next_step = str(parsed.get("next_step", "")).strip()
            if not intro:
                raise ValueError("LLM вернула пустое вступление")
            logger.info("OpenAI-совместимый провайдер: ответ получен")
            return intro, next_step or "Уточните запрос, чтобы сузить подбор."
        except Exception:  # noqa: BLE001 — любой сбой = откат на mock
            logger.exception(
                "Ошибка LLM-API, откатываемся на mock-формулировку"
            )
            return None


def _strip_code_fence(text: str) -> str:
    """Снять обрамление ```json … ``` если модель обернула ответ."""
    text = (text or "").strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
