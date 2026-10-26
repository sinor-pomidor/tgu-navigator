"""Конфигурация приложения.

Все настройки читаются из переменных окружения (и файла ``.env``)
через ``pydantic-settings``. Секреты в коде отсутствуют.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # База данных
    database_url: str = (
        "postgresql+psycopg2://navigator:navigator@localhost:5432/navigator"
    )

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
