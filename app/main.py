"""Точка входа FastAPI-приложения «ТГУ: Навигатор возможностей».

Подключает все роутеры API. Запуск:
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api import ask, health, opportunities
from app.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл приложения: инициализация схемы БД на старте."""
    init_db()
    logger.info("Приложение «ТГУ: Навигатор возможностей» запущено")
    yield


app = FastAPI(
    title="ТГУ: Навигатор возможностей",
    description=(
        "ИИ-ассистент для студентов ТГУ: подбор проектов, лабораторий, "
        "мероприятий и грантов на основе каталога проверенных возможностей."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(opportunities.router)
app.include_router(ask.router)
