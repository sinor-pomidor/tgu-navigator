"""Конфигурация приложения.

Все настройки читаются из переменных окружения (и файла ``.env``)
через ``pydantic-settings``. Секреты в коде отсутствуют.
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _bundle_root() -> Path | None:
    """Каталог exe-сборки (onefile PyInstaller) или ``None`` для обычного запуска.

    В onefile-режиме ``__file__`` указывает во временный каталог распаковки,
    поэтому данные (база, .env) нужно хранить рядом с самим exe.
    """
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


#: Файл локальной базы для режима «без Docker» (создаётся автоматически).
#: В .exe-сборке — рядом с exe, иначе — в ``data/`` внутри репозитория.
LOCAL_SQLITE_PATH = (_bundle_root() or Path(__file__).resolve().parent.parent) / "data" / "navigator.db"


def default_database_url() -> str:
    """Строка подключения по умолчанию.

    Если в окружении задан ``DATABASE_URL`` (облачный Postgres/Neon) —
    используется он; иначе — локальный SQLite-файл, что позволяет запускать
    приложение одной командой Python без Docker и без сервера PostgreSQL.

    Returns:
        Строка подключения SQLAlchemy.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return f"sqlite:///{LOCAL_SQLITE_PATH}"


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # База данных: Postgres (docker/облако) или SQLite (режим без Docker).
    database_url: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def _fill_default_db(cls, value: str | None) -> str:
        """Подставляет DATABASE_URL из окружения или путь к SQLite."""
        if not value:
            return default_database_url()
        return value

    # LLM-провайдер: mock | openai_compatible
    llm_provider: str = "mock"
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Telegram-бот
    tg_bot_token: str = ""

    # Окружение приложения: dev | prod
    app_env: str = "dev"

    # --- Конвейер сбора данных (ingestion) -----------------------------
    # Стартовые URL публичных страниц ТГУ для парсинга анонсов/новостей.
    # Можно переопределить через INGEST_START_URLS в .env (через запятую).
    ingest_start_urls: list[str] = [
        "https://news.tsu.ru/calendar-of-events/",
        "https://vestnik.tsu.ru/",
    ]
    # Задержка между запросами к сайту, сек (не превращаем сбор в DDoS).
    ingest_delay_seconds: float = 1.5
    # Сколько parsed-записей не подтверждалось источником, после чего они
    # автоматически переводятся в closed (дни).
    ingest_stale_days: int = 45


@lru_cache
def get_settings() -> Settings:
    """Возвращает singleton настроек приложения."""
    return Settings()
