"""Daily 21:00 reminder if no expense was logged today."""

from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.db import Database

log = logging.getLogger(__name__)

REMINDER_TEXT = (
    "Hey — nothing logged today yet.\n"
    "If you spent anything, just send it like:\n"
    "<code>15000 taksi</code>"
)


def setup_scheduler(bot: Bot, db: Database, user_id: int, timezone: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone)

    async def remind() -> None:
        try:
            if await db.has_expenses_today(user_id):
                log.info("Reminder skipped: expenses already logged today")
                return
            await bot.send_message(user_id, REMINDER_TEXT)
            log.info("Sent daily expense reminder")
        except Exception:
            log.exception("Failed to send daily reminder")

    scheduler.add_job(
        remind,
        CronTrigger(hour=21, minute=0, timezone=timezone),
        id="daily_expense_reminder",
        replace_existing=True,
    )
    return scheduler
