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
    setup_router(db, settings)
    dp.include_router(router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Botni ishga tushirish / Qo'llanma"),
            BotCommand(command="balans", description="Jami balans va hisobot"),
            BotCommand(command="daromad", description="Daromad kiritish (+3 mln maosh)"),
            BotCommand(command="set_weekly_money", description="Haftalik limit o'rnatish"),
            BotCommand(command="limit", description="Kategoriya bo'yicha oylik limit"),
            BotCommand(command="kunlik_maqsad", description="Kunlik xarajat maqsadi"),
            BotCommand(command="maqsad", description="Jamg'arma maqsadlari"),
            BotCommand(command="maqsad_yangi", description="Yangi jamg'arma maqsadi yaratish"),
            BotCommand(command="takroriy", description="Takroriy xarajatlar (Obunalar)"),
            BotCommand(command="maslahat", description="AI Moliyaviy maslahatchi (Gemini)"),
            BotCommand(command="stats", description="Diagramma va oylik tahlil"),
            BotCommand(command="today", description="Bugungi hisobot"),
            BotCommand(command="week", description="Bu haftalik hisobot"),
            BotCommand(command="month", description="Bu oylik hisobot"),
            BotCommand(command="export", description="Barcha xarajatlarni Excel'ga yuklash"),
        ]
    )

    await bot.set_my_description(
        "FinMate Bot — AI bilan jihozlangan aqlli shaxsiy moliya yordamchisi 💸\n\n"
        "✨ Qulayliklar:\n"
        "• Matn: \"kofega 15000 ketdi\"\n"
        "• Ovozli xabar kiritish 🎙\n"
        "• Chek rasmidan OCR o'qish 🧾\n"
        "• Byudjet va jamg'arma maqsadlari 🎯\n"
        "• AI Maslahatchi 🤖\n"
        "• Excel export & diagrammalar 📊"
    )

    await bot.set_my_short_description(
        "AI bilan jihozlangan aqlli shaxsiy moliya va byudjet boti 💸"
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
