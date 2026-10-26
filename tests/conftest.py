"""Общая фикстура тестов.

Тесты работают с реальным PostgreSQL (в разработке — локальный кластер или
контейнер ``db`` из docker-compose, см. README). Схема пересоздаётся из
моделей и наполняется сид-каталогом перед каждым прогоном, поэтому тесты
идемпотентны относительно состояния БД.

Модуль импортируется до приложения: переменные окружения задаются до
момента чтения настроек ``app.config``.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://navigator:navigator@localhost:5432/navigator",
)
os.environ["LLM_PROVIDER"] = "mock"  # ответы собираются без сети и ключей

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.seed import seed_database


@pytest.fixture(scope="session", autouse=True)
def prepared_database() -> None:
    """Создаёт схему и загружает сид-каталог один раз на прогон."""
    init_db()
    seed_database()


@pytest.fixture()
def db():
    """Сессия БД для сервисных тестов; закрывается после теста."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> TestClient:
    """HTTP-клиент FastAPI-приложения (тот же код, что в проде)."""
    from app.main import app

    return TestClient(app)
