"""Общая конфигурация тестов.

Жёсткие правила блока тестирования:

* тесты используют ОТДЕЛЬНУЮ базу ``tgu_test`` (боевая/демо-база не
  трогается): схема пересоздаётся из моделей и наполняется сид-каталогом
  перед прогоном;
* LLM-провайдер в тестах — только ``mock``: никаких сети и реальных ключей;
* Telegram-токен принудительно пустой — бот в тестах не запускается;
* каждый тест независим: сессия БД закрывается после теста, CRUD-тесты
  удаляют созданные записи через фикстуру ``cleanup_opportunity_ids``.

Модуль импортируется до приложения: переменные окружения задаются до
момента чтения настроек ``app.config`` и создания движка БД.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

# --- Окружение тестов: изолированная база, mock-LLM, без токенов. ---------
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://navigator:navigator@localhost:5432/tgu_test",
)
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["TG_BOT_TOKEN"] = ""

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import get_session_local, init_db
from app.models import Opportunity
from app.seed import seed_database


def _ensure_test_database() -> None:
    """Создаёт базу ``tgu_test``, если её ещё нет.

    Подключается к сервисной базе ``postgres`` и выполняет CREATE DATABASE.
    Требование изолированности выполняется жёстко: боевая/демо-база в
    тестах не используется никогда.
    """
    from app.config import get_settings

    url = make_url(get_settings().database_url)
    db_name = url.database or ""
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"Тесты обязаны работать на отдельной базе, а настроена "
            f"{db_name!r}. Проверьте TEST_DATABASE_URL — имя базы должно "
            f"содержать 'test'."
        )

    service_url = url.set(database="postgres")
    dsn = (
        f"host={service_url.host} port={service_url.port} "
        f"user={service_url.username} password={service_url.password or ''} "
        f"dbname=postgres"
    )
    conn = psycopg2.connect(dsn)
    conn.autocommit = True  # CREATE DATABASE требует autocommit-режима
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
            )
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def prepared_database() -> None:
    """Пересоздаёт схему тестовой базы и загружает сид-каталог на прогон."""
    _ensure_test_database()

    from app.config import get_settings

    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS opportunities CASCADE"))
    engine.dispose()

    init_db()
    seeded = seed_database()
    assert seeded > 0, "сид-каталог не загрузился в тестовую базу"


@pytest.fixture()
def db() -> Iterator[Session]:
    """Сессия БД для сервисных тестов; закрывается после теста."""
    session = get_session_local()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> TestClient:
    """HTTP-клиент FastAPI-приложения (тот же код, что в проде)."""
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def cleanup_opportunity_ids() -> Iterator[list[int]]:
    """Список id, созданных в тесте; записи удаляются после теста.

    Гарантирует независимость: тесты, создающие данные через API,
    не оставляют следов в каталоге для остальных тестов.
    """
    created: list[int] = []
    yield created
    if created:
        with get_session_local()() as session:
            session.query(Opportunity).filter(
                Opportunity.id.in_(created)
            ).delete(synchronize_session=False)
            session.commit()
