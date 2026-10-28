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

from sqlalchemy import JSON, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base, Opportunity

logger = logging.getLogger(__name__)



def _compile_tags_for_sqlite(element, compiler, **kw):  # noqa: ANN001, ARG001
    """DDL-компиляция колонки ``ARRAY(Text)`` для SQLite.

    В SQLite массивов нет — теги храним как TEXT (список строк сериализует
    сам тип ARRAY при записи). Хук применяется только диалектом SQLite.
    """
    return "TEXT"


try:  # pragma: no cover - импорт диалекта есть всегда вместе с SQLAlchemy
    from sqlalchemy.ext.compiler import compiles as _sqlalchemy_compiles
    from sqlalchemy.dialects.postgresql import ARRAY as _PG_ARRAY

    @_sqlalchemy_compiles(_PG_ARRAY, "sqlite")
    def _array_as_text_sqlite(element, compiler, **kw):  # noqa: ANN001
        return _compile_tags_for_sqlite(element, compiler, **kw)
except Exception:  # noqa: BLE001 - если хук не зарегистрировать, упадёт create_all
    logger.warning("Не удалось зарегистрировать DDL-хук ARRAY->TEXT для SQLite")

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
        url = normalize_database_url(get_settings().database_url)
        kwargs: dict[str, object] = {"echo": False}
        if url.startswith("sqlite"):
            # Локальный файл базы для режима «без Docker»; каталог создаём
            # автоматически, чтобы запуск не падал на пустом репозитории.
            from app.config import LOCAL_SQLITE_PATH

            if LOCAL_SQLITE_PATH.parent.exists() or "sqlite:///" in url:
                LOCAL_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_pre_ping"] = True
        _engine = create_engine(url, **kwargs)  # type: ignore[arg-type]

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


def init_db(seed_if_empty: bool = True) -> None:
    """Создаёт отсутствующие таблицы, расширения и (опционально) сид.

    На этапе прототипа миграции не используются — схема разворачивается
    через ``Base.metadata.create_all`` при старте приложения. Поддержаны
    два типа баз:

    * PostgreSQL (docker-compose / облачный Postgres) — добавляются
      расширение pg_trgm и GIN-индексы полнотекстового поиска;
    * SQLite (режим «без Docker», файл ``data/navigator.db``) —
      специфичные для Postgres конструкции пропускаются, поиск работает
      в деградированном ILIKE-режиме (см. app/services/search.py).

    Args:
        seed_if_empty: если таблица пуста — загрузить стартовый каталог
            из ``seed/opportunities.json``, чтобы пользователь получил
            рабочую базу сразу после первого запуска.
    """
    eng = get_engine()
    is_sqlite = eng.dialect.name == "sqlite"

    if not is_sqlite:
        # Расширения, необходимые для гибридного поиска (см. Задачу 5).
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
    _ensure_ingest_columns(eng)
    if not is_sqlite:
        for index in Opportunity.postgres_only_indexes():
            index.create(bind=eng, checkfirst=True)
    logger.info("Схема базы данных инициализирована (%s)", eng.dialect.name)

    if seed_if_empty:
        _seed_if_empty()


def _seed_if_empty() -> None:
    """Загружает стартовый каталог, если таблица возможностей пуста."""
    from sqlalchemy import func, select

    from app.seed import DEFAULT_SEED_PATH, seed_database

    with session_scope() as db:
        count = db.scalar(select(func.count()).select_from(Opportunity))
    if count:
        return
    if not DEFAULT_SEED_PATH.exists():
        logger.warning("Сид-файл не найден: %s", DEFAULT_SEED_PATH)
        return
    loaded = seed_database(DEFAULT_SEED_PATH)
    logger.info("База была пуста — загружено %d записей каталога", loaded)


def _ensure_ingest_columns(eng: Engine) -> None:
    """Идемпотно добавляет колонки ingestion в существующую таблицу.

    Миграций (Alembic) на этапе прототипа нет, поэтому базы, созданные до
    появления полей ``origin``/``last_seen_at``/``external_id``, дополняются
    ими на старте. Повторный запуск безопасен: колонки проверяются по
    ``PRAGMA table_info`` / ``information_schema`` и создаются только при
    отсутствии. Идемпотентный аналог app/migrations/add_origin_fields.py.
    """
    from sqlalchemy import inspect

    try:
        existing = {c["name"] for c in inspect(eng).get_columns("opportunities")}
    except Exception:  # noqa: BLE001 - таблицы ещё может не быть
        return
    statements: list[str] = []
    if "origin" not in existing:
        statements.append(
            "ALTER TABLE opportunities ADD COLUMN origin VARCHAR(10) NOT NULL DEFAULT 'manual'"
        )
    if "last_seen_at" not in existing:
        statements.append("ALTER TABLE opportunities ADD COLUMN last_seen_at DATETIME")
    if "external_id" not in existing:
        statements.append("ALTER TABLE opportunities ADD COLUMN external_id TEXT")
    if not statements:
        return
    with eng.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    logger.info("Добавлены недостающие колонки ingestion: %d", len(statements))


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
