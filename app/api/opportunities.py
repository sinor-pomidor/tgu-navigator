"""CRUD-эндпоинты каталога возможностей (Задача 4).

GET    /opportunities        — список с фильтрами type/status/q
GET    /opportunities/{id}   — одна запись
POST   /opportunities        — создание
PUT    /opportunities/{id}   — частичное/полное обновление
DELETE /opportunities/{id}   — удаление

Валидация входных данных выполняется Pydantic-схемами (код 422 генерирует
FastAPI автоматически), отсутствующая запись даёт 404.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Opportunity as OpportunityModel
from app.models import OpportunityStatus, OpportunityType
from app.schemas import Opportunity, OpportunityCreate, OpportunityUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=list[Opportunity])
def list_opportunities(
    db: Session = Depends(get_db),
    type: OpportunityType | None = Query(default=None, description="Фильтр по типу"),
    status_filter: OpportunityStatus | None = Query(
        default=None, alias="status", description="Фильтр по статусу"
    ),
    q: str | None = Query(
        default=None, min_length=1, max_length=200,
        description="Подстрока по названию/описанию/тегам",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[OpportunityModel]:
    """Возвращает список возможностей с фильтрами и пагинацией."""
    stmt = select(OpportunityModel)
    if type is not None:
        stmt = stmt.where(OpportunityModel.type == type)
    if status_filter is not None:
        stmt = stmt.where(OpportunityModel.status == status_filter)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                OpportunityModel.title.ilike(pattern),
                OpportunityModel.description.ilike(pattern),
                # Массив тегов приводим к тексту для поиска подстроки.
                func.array_to_string(OpportunityModel.tags, " ").ilike(pattern),
            )
        )
    stmt = stmt.order_by(OpportunityModel.id).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.get("/{opportunity_id}", response_model=Opportunity)
def get_opportunity(
    opportunity_id: int, db: Session = Depends(get_db)
) -> OpportunityModel:
    """Возвращает запись по id; 404, если её нет."""
    obj = db.get(OpportunityModel, opportunity_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Возможность id={opportunity_id} не найдена",
        )
    return obj


@router.post(
    "", response_model=Opportunity, status_code=status.HTTP_201_CREATED
)
def create_opportunity(
    payload: OpportunityCreate, db: Session = Depends(get_db)
) -> OpportunityModel:
    """Создаёт новую запись каталога."""
    obj = OpportunityModel(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    logger.info("Создана возможность id=%s title=%s", obj.id, obj.title)
    return obj


@router.put("/{opportunity_id}", response_model=Opportunity)
def update_opportunity(
    opportunity_id: int,
    payload: OpportunityUpdate,
    db: Session = Depends(get_db),
) -> OpportunityModel:
    """Обновляет переданные поля записи; 404, если записи нет."""
    obj = db.get(OpportunityModel, opportunity_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Возможность id={opportunity_id} не найдена",
        )
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    logger.info("Обновлена возможность id=%s (полей: %s)", obj.id, len(changes))
    return obj


@router.delete(
    "/{opportunity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_opportunity(
    opportunity_id: int, db: Session = Depends(get_db)
) -> Response:
    """Удаляет запись; 404, если её нет."""
    obj = db.get(OpportunityModel, opportunity_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Возможность id={opportunity_id} не найдена",
        )
    db.delete(obj)
    db.commit()
    logger.info("Удалена возможность id=%s", opportunity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
