"""Подключение к базе данных и работа с сессиями SQLAlchemy.

Модуль создаёт движок по ``DATABASE_URL`` из конфигурации, обеспечивает
инициализацию схемы (``create_all``) на этапе прототипа и предоставляет
зависимость FastAPI для получения сессии на один запрос.

Строка подключения приводится к драйверу psycopg2: если в ``DATABASE_URL``
указан другой драйвер (например, ``postgresql+asyncpg://``), он заменяется
на ``postgresql+psycopg2://`` — проект использует синхронный SQLAlchemy.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

settings = get_settings()


def normalize_database_url(url: str) -> str:
    """Приводит схему драйвера строки подключения к psycopg2.

    Args:
        url: исходная строка подключения из конфигурации.

    Returns:
        Строка подключения с драйвером ``postgresql+psycopg2``.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if "+psycopg2" not in url and url.startswith("postgresql+"):
        rest = url.split("://", 1)
        scheme = rest[0].split("+", 1)[0]
        return f"{scheme}+psycopg2://{rest[1]}"
    return url


engine: Engine = create_engine(
    normalize_database_url(settings.database_url),
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Создаёт отсутствующие таблицы и расширения БД.

    На этапе прототипа миграции не используются — схема разворачивается
    через ``Base.metadata.create_all`` при старте приложения. Индексы
    pg_trgm создаваются только если расширение ``pg_trgm`` доступно;
    при его отсутствии приложение продолжает работу без них.
    """
    # Расширения, необходимые для гибридного поиска (см. Задачу 5).
    for extension in ("pg_trgm",):
        try:
            with engine.begin() as conn:
                conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
            logger.info("Расширение %s проверено/подключено", extension)
        except Exception:  # noqa: BLE001 - прототип: деградируем мягко
            logger.warning(
                "Расширение %s недоступно (ожидаем образ pgvector/pgvector:pg16)",
                extension,
                exc_info=True,
            )

    Base.metadata.create_all(bind=engine)
    logger.info("Схема базы данных инициализирована (create_all)")


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Контекстный менеджер сессии: коммитит при успехе, откатывает при ошибке."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Зависимость FastAPI: выдаёт сессию БД на время обработки запроса."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
