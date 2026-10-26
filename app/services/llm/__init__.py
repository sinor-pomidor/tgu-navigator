"""Абстракция LLM-провайдеров для сборки ответа (Задача 6).

Модуль изолирует продукт от конкретного вендора моделей: весь код
приложения зависит только от интерфейса ``LLMProvider`` и фабрики
``get_provider``, которая выбирает реализацию по настройке
``LLM_PROVIDER`` из окружения.

Реализации:
* ``mock.MockProvider`` — детерминированная сборка ответа по шаблонам,
  работает без сети и ключей (провайдер по умолчанию);
* ``openai_compatible.OpenAICompatibleProvider`` — любой OpenAI-совместимый
  chat-completions API через httpx; включается только при явной настройке.
"""

from app.services.llm.base import (
    Answer,
    AnswerCard,
    LLMProvider,
    get_provider,
)

__all__ = ["Answer", "AnswerCard", "LLMProvider", "get_provider"]
