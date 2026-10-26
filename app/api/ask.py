"""Эндпоинт главного сценария: POST /ask (Задача 6).

Принимает свободный запрос студента, запускает гибридный поиск по каталогу
и возвращает структурированный JSON-ответ (вступление, карточки, следующий
шаг, источники), собранный активным LLM-провайдером (по умолчанию — mock,
работает без интернета и ключей).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import AskRequest, AskResponse
from app.services.answer import build_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
@router.post("/", response_model=AskResponse, include_in_schema=False)
def ask(payload: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    """Подобрать возможности по запросу пользователя.

    Args:
        payload: тело запроса с полем ``query``.
        db: сессия БД (внедряется FastAPI).

    Returns:
        Структурированный ответ; в нём ВСЕГДА есть поле ``sources``.

    Raises:
        HTTPException 500 — если сборка ответа неожиданно упала
        (например, БД недоступна).
    """
    try:
        data = build_answer(payload.query, db)
    except Exception as exc:  # noqa: BLE001 — граничный обработчик API
        logger.exception("Ошибка при сборке ответа на запрос %r", payload.query)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сформировать ответ, попробуйте позже",
        ) from exc
    return AskResponse(**data)
