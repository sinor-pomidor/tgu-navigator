"""Точка входа FastAPI-приложения «ТГУ: Навигатор возможностей».

Подключает все роутеры API. Запуск:
    uvicorn app.main:app --reload
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import ask, health, opportunities
from app.db import init_db

#: Каталог ресурсов: в .exe-сборке (onefile PyInstaller) frontend и seed
#: упакованы внутрь временного каталога распаковки ``sys._MEIPASS``;
#: при обычном запуске из исходников — корень репозитория.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
FRONTEND_DIR = BUNDLE_DIR / "frontend"
#: Версия приложения: берётся из тега релиза, зашитого сборщиком (.exe),
#: иначе — из значения по умолчанию для обычных запусков из исходников.
APP_VERSION = os.environ.get("TGU_APP_VERSION", "0.3.4")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл приложения: схема БД и автозаполнение каталога на старте.

    Для .exe-сборки (``TGU_BUNDLE=1``) база может быть пустой или битой после
    обновления программы — при любом сбое инициализации удаляется локальный
    SQLite-файл и всё создаётся заново, затем каталог загружается из seed.
    Так запуск exe не зависит от состояния окружения пользователя.
    """
    try:
        init_db()
        _ensure_catalog()
        _refresh_deadline_statuses()
    except Exception:  # noqa: BLE001 - аварийное самовосстановление для exe
        if os.environ.get("TGU_BUNDLE") == "1":
            logger.warning("Первый старт не удался, пересоздаю локальную базу...")
            from app.config import LOCAL_SQLITE_PATH

            LOCAL_SQLITE_PATH.unlink(missing_ok=True)
            init_db()
        _ensure_catalog(force=True)
        _refresh_deadline_statuses()
    logger.info("Приложение «ТГУ: Навигатор возможностей» запущено")
    yield


def _refresh_deadline_statuses() -> None:
    """Автообновление статусов по дедлайну при старте приложения.

    Просроченные возможности (дедлайн прошёл) переводятся в ``closed``,
    близкие к закрытию — в ``closing_soon``; поиск показывает только живые
    записи, поэтому без этого шага каталог мог бы «застыть» в статусах,
    записанных в seed/CSV вручную.
    """
    from app.db import session_scope
    from app.ingestion.normalize import refresh_statuses

    with session_scope() as session:
        changed = refresh_statuses(session)
    if changed:
        logger.info("Автообновление статусов на старте: изменено %d", changed)


def _ensure_catalog(force: bool = False) -> None:
    """Загружает seed-каталог, если таблица пуста (или по ``force``)."""
    from sqlalchemy import func, select

    from app.db import session_scope
    from app.models import Opportunity

    with session_scope() as session:
        count = session.scalar(select(func.count()).select_from(Opportunity))
    if count == 0 or force:
        from app.seed import seed_database

        seed_path = BUNDLE_DIR / "seed" / "opportunities.json"
        if not seed_path.is_file():
            seed_path = FRONTEND_DIR.parent / "seed" / "opportunities.json"
        if seed_path.is_file():
            seed_database(seed_path)


app = FastAPI(
    title="ТГУ: Навигатор возможностей",
    description=(
        "ИИ-ассистент для студентов ТГУ: подбор проектов, лабораторий, "
        "мероприятий и грантов на основе каталога проверенных возможностей."
    ),
    version=APP_VERSION,
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
