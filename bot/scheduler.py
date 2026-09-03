"""Scheduled background jobs (daily reminder at 21:00 and end-of-month report)."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.chart import generate_category_pie_chart
from bot.db import Database
from bot.parser import format_money

log = logging.getLogger(__name__)

REMINDER_TEXT = (
    "🔔 <b>Kunlik eslatma:</b>\n"
    "Bugun xarajat yozishni unutdingizmi?\n"
    "Masalan: <code>kofega 15000 ketdi</code>"
)


def setup_scheduler(bot: Bot, db: Database, user_id: int | None, timezone: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone)

    async def daily_remind() -> None:
        user_ids = [user_id] if user_id is not None else await db.get_active_user_ids()
        for uid in user_ids:
            if not uid:
                continue
            try:
                if await db.has_expenses_today(uid):
                    log.info("Reminder skipped for %s: expenses already logged today", uid)
                    continue
                await bot.send_message(uid, REMINDER_TEXT)
                log.info("Sent daily expense reminder to %s", uid)
            except Exception as e:
                log.exception("Failed to send daily reminder to %s: %s", uid, e)

    async def end_of_month_summary() -> None:
        user_ids = [user_id] if user_id is not None else await db.get_active_user_ids()
        for uid in user_ids:
            if not uid:
                continue
            try:
                start, end = db.month_range()
                rows = await db.expenses_between(uid, start, end)
                if not rows:
                    continue

                income = sum(int(r["amount"]) for r in rows if r.get("type") == "income")
                expense = sum(int(r["amount"]) for r in rows if r.get("type") == "expense")
                cat_totals = await db.get_category_totals(uid, start, end)

                msg = (
                    "📅 <b>Oy Yakuni Bo'yicha Xulosa Hisoboti!</b>\n\n"
                    f"💰 Jami kirim: <b>{format_money(income)} so'm</b>\n"
                    f"💸 Jami xarajat: <b>{format_money(expense)} so'm</b>\n"
                    f"💵 Sof qoldiq: <b>{format_money(income - expense)} so'm</b>"
                )

                chart_bytes = generate_category_pie_chart(cat_totals, title="Oylik Yakuniy Diagramma")
                if chart_bytes:
                    photo = BufferedInputFile(chart_bytes, filename="end_of_month.png")
                    await bot.send_photo(uid, photo, caption=msg)
                else:
                    await bot.send_message(uid, msg)

                log.info("Sent end of month summary to %s", uid)
            except Exception as e:
                log.exception("Failed to send month end summary to %s: %s", uid, e)

    # Daily reminder at 21:00
    scheduler.add_job(
        daily_remind,
        CronTrigger(hour=21, minute=0, timezone=timezone),
        id="daily_expense_reminder",
        replace_existing=True,
    )

    # End of month summary on the last day of month at 21:00
    scheduler.add_job(
        end_of_month_summary,
        CronTrigger(day="last", hour=21, minute=0, timezone=timezone),
        id="end_of_month_summary",
        replace_existing=True,
    )

    return scheduler
