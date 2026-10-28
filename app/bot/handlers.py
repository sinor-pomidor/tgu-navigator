"""Хендлеры Telegram-бота (Задача 7): /start и обработка текстовых запросов.

Сценарий полностью переиспользует сервис ``app.services.answer.build_answer``
— тот же код, что стоит за POST /ask. Ответ бота: вступительный текст +
карточки возможностей (эмодзи типа, название, суть, требования, срок,
контакт) с inline-кнопкой «Подробнее», ведущей на официальный источник.

Все обращения к БД выполняются в thread executor, чтобы не блокировать
event loop aiogram.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.answer import build_answer

logger = logging.getLogger(__name__)

router = Router()

#: Эмодзи по типам возможностей для карточек.
_TYPE_EMOJI: dict[str, str] = {
    "project": "🚀",
    "lab": "🔬",
    "event": "📅",
    "grant": "💰",
}

_WELCOME_TEXT = (
    "👋 Привет! Я — «ТГУ: Навигатор возможностей».\n\n"
    "Расскажите обычными словами, что вы ищете, — я подберу подходящие "
    "проекты, лаборатории, мероприятия и гранты ТГУ из проверенного "
    "каталога и пришлю ссылки на официальные источники.\n\n"
    "Примеры запросов:\n"
    "• «Я учусь на Инноватике, интересуюсь ИИ и хочу попасть в реальный проект»\n"
    "• «Грант на стартап для магистранта»\n"
    "• «Хочу в лабораторию, где занимаются анализом данных»\n"
    "• «Какие хакатоны скоро пройдут?»"
)


def _format_deadline(value: str | None) -> str | None:
    """Преобразовать ISO-дату карточки в человекочитаемый формат (дд.мм.гггг)."""
    if not value:
        return None
    try:
        return date.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return value


def _card_text(card: dict) -> str:
    """Собрать текст одной карточки ответа."""
    emoji = _TYPE_EMOJI.get(str(card.get("type")), "ℹ️")
    lines = [f"{emoji} <b>{card['title']}</b>", card.get("summary", "")]
    requirements = card.get("requirements")
    if requirements:
        lines.append(f"Требования: {requirements}")
    deadline = _format_deadline(card.get("deadline"))
    if deadline:
        status_note = " ⏰ скорое закрытие" if card.get("status") == "closing_soon" else ""
        lines.append(f"Срок: до {deadline}{status_note}")
    contact = card.get("contact")
    if contact:
        lines.append(f"Контакт: {contact}")
    return "\n".join(line for line in lines if line)


def _details_keyboard(url: str) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура с единственной кнопкой-ссылкой «Подробнее»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Подробнее 🔗", url=url)]]
    )


async def _answer_query(query: str) -> dict:
    """Вызвать сценарий /ask в отдельном потоке (БД-синхронный)."""

    def _run() -> dict:
        db: Session = SessionLocal()
        try:
            return build_answer(query, db)
        finally:
            db.close()

    return await asyncio.to_thread(_run)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Команда /start — приветствие и подсказки о формате запроса."""
    await message.answer(_WELCOME_TEXT)


@router.message(F.text)
async def handle_text(message: Message) -> None:
    """Любое текстовое сообщение → сценарий подбора → карточки с кнопками."""
    query = (message.text or "").strip()
    if not query:
        await message.answer(
            "Пришлите текстом, что вы ищете — например: «хочу в проект по ИИ»."
        )
        return

    logger.info("Бот: запрос от пользователя %s: %r", message.chat.id, query)
    try:
        data = await _answer_query(query)
    except Exception:  # noqa: BLE001 — диалог с пользователем не должен падать
        logger.exception("Бот: ошибка при обработке запроса %r", query)
        await message.answer(
            "😔 Сейчас не удалось подготовить подборку — база данных "
            "недоступна. Попробуйте немного позже."
        )
        return

    if not data.get("found"):
        await message.answer(
            f"{data['intro']}\n\n{data['next_step']}",
            disable_web_page_preview=True,
        )
        return

    await message.answer(data["intro"], disable_web_page_preview=True)
    for card in data["cards"]:
        await message.answer(
            _card_text(card),
            reply_markup=_details_keyboard(card["source_url"]),
            disable_web_page_preview=True,
        )
    await message.answer(data["next_step"])
