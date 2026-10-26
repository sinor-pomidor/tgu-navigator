"""Подключение к базе данных и работа с сессиями SQLAlchemy.

Модуль создаёт движок по ``DATABASE_URL`` из конфигурации, обеспечивает
инициализацию схемы (``create_all``) на этапе прототипа и предоставляет
зависимость FastAPI для получения сессии на один запрос.
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

engine: Engine = create_engine(
    settings.database_url,
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
