"""Точка входа FastAPI-приложения «ТГУ: Навигатор возможностей».

Подключает все роутеры API. Запуск:
    uvicorn app.main:app --reload
"""

import logging

from fastapi import FastAPI

from app.api import health
from app.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ТГУ: Навигатор возможностей",
    description=(
        "ИИ-ассистент для студентов ТГУ: подбор проектов, лабораторий, "
        "мероприятий и грантов на основе каталога проверенных возможностей."
    ),
    version="0.1.0",
)

app.include_router(health.router)


@app.on_event("startup")
def on_startup() -> None:
    """Событие запуска: инициализация схемы БД и логирование старта."""
    init_db()
    logger.info("Приложение «ТГУ: Навигатор возможностей» запущено")
