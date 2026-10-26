"""Точка входа Telegram-бота (Задача 7).

Запуск:
    python -m app.bot.bot

Токен берётся из переменной окружения TG_BOT_TOKEN (.env). Если токен не
задан, процесс НЕ падает с трейсбеком — в консоль выводится понятное
сообщение с инструкцией и код завершения 1.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from app.bot.handlers import router
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_bot(token: str) -> None:
    """Зарегистрировать хендлеры и запустить long polling."""
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    logger.info("Telegram-бот запускается (long polling)…")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> int:
    """Синхронная обёртка запуска; возвращает код завершения процесса."""
    settings = get_settings()
    token = (settings.tg_bot_token or "").strip()
    if not token:
        logger.error(
            "TG_BOT_TOKEN не задан — запуск бота невозможен.\n"
            "Получите токен у @BotFather и пропишите его в файл .env:\n"
            "    TG_BOT_TOKEN=123456:ABC-your-token\n"
            "После этого повторите: python -m app.bot.bot"
        )
        return 1

    try:
        asyncio.run(run_bot(token))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Telegram-бот остановлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
