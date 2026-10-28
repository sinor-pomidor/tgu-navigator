"""Точка входа FastAPI-приложения «ТГУ: Навигатор возможностей».

Подключает все роутеры API. Запуск:
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import ask, health, opportunities
from app.db import init_db

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

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
    version="0.2.5",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(opportunities.router)
app.include_router(ask.router)

# CORS: чтобы фронтенд, открытый с другого адреса (например, file:// или
# локальный статический сервер), мог обращаться к API. В прототипе — все
# источники; на боевом окружении список следует сузить.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статический MVP-фронтенд: frontend/index.html раздаётся по адресу "/"
# (html=True возвращает index.html для запроса к директории). Монтируется
# последним, чтобы не перекрывать /docs, /health, /ask и /opportunities.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
