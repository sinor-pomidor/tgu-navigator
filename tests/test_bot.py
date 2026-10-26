"""Тесты Telegram-бота (без сети и без реального токена).

Telegram API не вызывается: хендлеры получают фейковые сообщения-шпионы,
которые лишь записывают аргументы ``answer``. Сценарий подбора — реальный
(mock-провайдер + тестовая база), поэтому проверяется сквозная логика бота:
/start, карточки с кнопками-ссылками, честный ответ «не найдено» и то,
что процесс запуска не падает без токена.
"""

from __future__ import annotations

from typing import Any

import asyncio as _asyncio
from sqlalchemy.orm import Session

from app.bot import bot as bot_module
from app.bot.handlers import (
    _answer_query,
    _card_text,
    _details_keyboard,
    cmd_start,
    handle_text,
)


class FakeMessage:
    """Шпион aiogram-сообщения: пишет вызовы answer в список."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.chat = type("Chat", (), {"id": 1})()
        self.sent: list[dict[str, Any]] = []

    async def answer(self, content: str, **kwargs: Any) -> None:
        self.sent.append({"text": content, **kwargs})


def run(coro: Any) -> Any:
    """Запустить корутину хендлера в событийном цикле (без сети и токена)."""
    return _asyncio.run(coro)


# ------------------------------ /start ---------------------------------


def test_start_sends_welcome_with_examples() -> None:
    """/start → приветствие на русском с примерами запросов."""
    message = FakeMessage("/start")
    run(cmd_start(message))

    assert len(message.sent) == 1
    text = message.sent[0]["text"]
    assert "Привет" in text
    for hint in ("проект", "лаборатор", "грант", "хакатон"):
        assert hint.lower() in text.lower() or hint == "хакатон"


# ------------------------- текстовый запрос ----------------------------


def test_text_query_answers_intro_cards_and_next_step() -> None:
    """Текст → вступление + по сообщению на карточку + следующий шаг."""
    message = FakeMessage("хочу в проект по ИИ")
    run(handle_text(message))

    assert message.sent, "бот обязан ответить"
    intro = message.sent[0]["text"]
    last = message.sent[-1]["text"]
    assert intro and last

    # Карточки: у каждой есть инлайн-кнопка «Подробнее» со ссылкой источника.
    card_messages = [m for m in message.sent if "reply_markup" in m]
    assert card_messages, "в подборке должны быть карточки с кнопками"
    for m in card_messages:
        keyboard = m["reply_markup"]
        url = keyboard.inline_keyboard[0][0].url
        assert url.startswith("http"), "кнопка ведёт на официальный источник"


def test_card_text_contains_title_deadline_contact_emoji() -> None:
    """Формат карточки: эмодзи типа, название, срок, контакт."""
    payload = run(_answer_query("хочу в проект по ИИ"))
    card = payload["cards"][0]
    text = _card_text(card)

    assert card["title"] in text
    assert "<b>" in text  # заголовок выделен
    if card["deadline"]:
        assert "Срок:" in text
    if card["contact"]:
        assert "Контакт:" in text


def test_not_found_gets_polite_advice() -> None:
    """Пустая выдача → вежливое сообщение с советом переформулировать."""
    message = FakeMessage("гонки на квантовых единорогах")
    run(handle_text(message))

    assert len(message.sent) == 1
    text = message.sent[0]["text"].lower()
    assert "не" in text and ("переформул" in text or "попробуйте" in text)


def test_empty_text_prompted_for_query() -> None:
    """Пустое/пробельное сообщение → просьба описать запрос словами."""
    message = FakeMessage("   ")
    run(handle_text(message))
    assert message.sent and message.sent[0]["text"]


# --------------------- запуск без токена (деградация) ------------------


def test_main_without_token_returns_error_code(monkeypatch, caplog) -> None:
    """Без TG_BOT_TOKEN main() не бросает исключение: код 1 и понятный текст."""
    fake_settings = type("S", (), {"tg_bot_token": ""})()
    monkeypatch.setattr(bot_module, "get_settings", lambda: fake_settings)

    with caplog.at_level("ERROR"):
        code = bot_module.main()

    assert code == 1
    assert any("TG_BOT_TOKEN" in rec.message for rec in caplog.records)


def test_keyboard_button_url_is_source_link() -> None:
    """Клавиатура «Подробнее» — одна кнопка-ссылка с переданным URL."""
    kb = _details_keyboard("https://example.edu/source")
    button = kb.inline_keyboard[0][0]
    assert button.url == "https://example.edu/source"
    assert "Подробнее" in button.text
