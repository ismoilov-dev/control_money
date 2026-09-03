"""Entry point: Telegram long-polling + daily reminder."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import load_settings
from bot.db import Database
from bot.handlers import router, setup_router
from bot.scheduler import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("expense-bot")


async def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path, timezone=settings.timezone)
    await db.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    setup_router(db, settings.allowed_user_id)
    dp.include_router(router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="How to log expenses"),
            BotCommand(command="today", description="Today's spending"),
            BotCommand(command="week", description="This week's spending"),
            BotCommand(command="month", description="This month's spending"),
            BotCommand(command="categories", description="View or edit categories"),
            BotCommand(command="delete_last", description="Undo last expense"),
        ]
    )

    scheduler = setup_scheduler(
        bot=bot,
        db=db,
        user_id=settings.allowed_user_id,
        timezone=settings.timezone,
    )
    scheduler.start()
    log.info("Daily reminder scheduled for 21:00 %s", settings.timezone)

    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Starting polling")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
