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


#: Глобальные engine/SessionLocal создаются лениво (см. get_engine()),
#: чтобы тесты могли подменить DATABASE_URL на изолированную базу до
#: первого обращения к слою доступа к данным.
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Возвращает singleton движка SQLAlchemy (ленивое создание).

    Движок создаётся при первом обращении — после загрузки конфигурации,
    что позволяет окружению (в т.ч. ``DATABASE_URL`` в тестах) полностью
    определить строку подключения.

    Returns:
        Активный ``Engine`` приложения.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(
            normalize_database_url(get_settings().database_url),
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_local() -> sessionmaker[Session]:
    """Возвращает singleton фабрики сессий поверх ``get_engine()``."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False
        )
    return _SessionLocal


# Обратная совместимость: SessionLocal доступен как раньше — но фабрикой
# он становится лениво; вызов SessionLocal() открывает сессию текущей базы.
class _SessionLocalProxy(sessionmaker[Session]):
    """Прокси ``SessionLocal``: прокидывает вызовы в ленивую фабрику."""

    def __call__(self, **kwargs):  # type: ignore[override]
        return get_session_local()(**kwargs)

    def __getattr__(self, name: str):
        return getattr(get_session_local(), name)


SessionLocal = _SessionLocalProxy()


def init_db() -> None:
    """Создаёт отсутствующие таблицы и расширения БД.

    На этапе прототипа миграции не используются — схема разворачивается
    через ``Base.metadata.create_all`` при старте приложения. Индексы
    pg_trgm создаваются только если расширение ``pg_trgm`` доступно;
    при его отсутствии приложение продолжает работу без них.
    """
    # Расширения, необходимые для гибридного поиска (см. Задачу 5).
    eng = get_engine()
    for extension in ("pg_trgm",):
        try:
            with eng.begin() as conn:
                conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
            logger.info("Расширение %s проверено/подключено", extension)
        except Exception:  # noqa: BLE001 - прототип: деградируем мягко
            logger.warning(
                "Расширение %s недоступно (ожидаем образ pgvector/pgvector:pg16)",
                extension,
                exc_info=True,
            )

    Base.metadata.create_all(bind=eng)
    logger.info("Схема базы данных инициализирована (create_all)")


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Контекстный менеджер сессии: коммитит при успехе, откатывает при ошибке."""
    session = get_session_local()()
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
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
