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


@lru_cache
def get_settings() -> Settings:
    """Возвращает singleton настроек приложения."""
    return Settings()
