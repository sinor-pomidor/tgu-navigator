"""Сервис сборки ответа (Задача 6): связка «поиск → LLM-провайдер → ответ».

Вынесено в отдельный сервис, чтобы его могли переиспользовать и REST-API
(`POST /ask`), и Telegram-бот — обе поверхности используют один и тот же
сценарий «запрос → подборка с источниками».
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.services.llm import get_provider
from app.services.search import search

logger = logging.getLogger(__name__)


def build_answer(query: str, db: Session) -> dict:
    """Главный сценарий продукта: по фразе пользователя собрать подборку.

    Args:
        query: свободная формулировка запроса студента.
        db: активная сессия БД.

    Returns:
        Словарь-ответ: ``query``, ``found``, ``intro``, ``cards``,
        ``next_step``, ``sources`` (поле ``sources`` присутствует ВСЕГДА).
    """
    results = search(query, db=db)
    logger.info("Поиск по запросу %r: %d результатов", query, len(results))
    answer = get_provider().compose_answer(query, results)
    payload = answer.to_dict()
    payload["query"] = query.strip()
    return payload
