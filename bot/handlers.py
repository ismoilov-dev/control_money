"""Command and free-text transaction handlers (multi-user budget tracker)."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, TelegramObject

from bot.db import Database
from bot.parser import format_money, parse_expense

log = logging.getLogger(__name__)
router = Router()


class DbMiddleware(BaseMiddleware):
    """Inject database dependency into event data for all users."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        return await handler(event, data)


def setup_router(db: Database) -> Router:
    middleware = DbMiddleware(db)
    router.message.outer_middleware(middleware)
    return router


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Moliya botiga xush kelibsiz!\n\n"
        "<b>Qanday ishlatiladi:</b>\n"
        "1️⃣ Haftalik pulingizni kiriting:\n"
        "   <code>/set_weekly_money 300k</code>\n\n"
        "2️⃣ Xarajatlarni minus (-) bilan yoki oddiy yozing:\n"
        "   • <code>-12 taksi</code> (12 000 so'm)\n"
        "   • <code>-150 ovqat</code> (150 000 so'm)\n"
        "   • <code>30 taksi</code> (30 000 so'm)\n\n"
        "3️⃣ Kirimlarni plyus (+) bilan yozing:\n"
        "   • <code>+3000000 maosh</code>\n\n"
        "<b>Buyruqlar:</b>\n"
        "/set_weekly_money 300k — Haftalik pul o'rnatish\n"
        "/today — Bugungi hisobot\n"
        "/week — Bu haftalik hisobot va qoldiq\n"
        "/month — Bu oylik hisobot"
    )


@router.message(Command("set_weekly_money", "set_weekly_limit", "set_week_limit"))
async def cmd_set_weekly_money(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Haftalik pulni o'rnatish uchun buyruqni bering:\n"
            "<code>/set_weekly_money 300k</code>"
        )
        return
    parsed = parse_expense(args[1])
    if parsed is None or parsed.amount <= 0:
        await message.answer(
            "Noto'g'ri summa kiritildi. Masalan: <code>/set_weekly_money 300k</code>"
        )
        return
    user_id = message.from_user.id if message.from_user else 0
    await db.set_weekly_limit(parsed.amount, user_id=user_id)
    await message.answer(
        f"✅ Haftalik pul o'rnatildi: <b>{format_money(parsed.amount)} so'm</b>"
    )


@router.message(Command("today"))
async def cmd_today(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    start, end = db.day_range()
    rows = await db.expenses_between(user_id, start, end)
    weekly_limit = await db.get_weekly_limit(user_id=user_id)
    await message.answer(_render_report("Bugungi hisobot", rows, weekly_limit=weekly_limit))


@router.message(Command("week"))
async def cmd_week(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    start, end = db.week_range()
    rows = await db.expenses_between(user_id, start, end)
    weekly_limit = await db.get_weekly_limit(user_id=user_id)
    await message.answer(_render_report("Bu haftalik hisobot", rows, weekly_limit=weekly_limit))


@router.message(Command("month"))
async def cmd_month(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    start, end = db.month_range()
    rows = await db.expenses_between(user_id, start, end)
    await message.answer(_render_report("Bu oylik hisobot", rows))


@router.message(F.text)
async def on_text(message: Message, db: Database) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    parsed = parse_expense(text)
    if parsed is None:
        await message.answer(
            "Summani aniqlay olmadim. Masalan:\n"
            "<code>-12 taksi</code> yoki <code>+3000000 maosh</code>"
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    category = "Kirim" if parsed.type == "income" else "Xarajat"
    description = parsed.description or ("xarajat" if parsed.type == "expense" else "kirim")

    await db.add_expense(
        user_id,
        parsed.amount,
        category,
        description,
        type=parsed.type,
    )

    desc_str = f" ({description})" if description and description != str(parsed.amount) else ""

    if parsed.type == "income":
        await message.answer(
            f"💰 Kirim saqlandi: +{format_money(parsed.amount)} so'm{desc_str}"
        )
    else:
        await message.answer(
            f"💸 Xarajat saqlandi: {format_money(parsed.amount)} so'm{desc_str}"
        )
        warnings = await check_spending_limit_warnings(db, user_id)
        for w in warnings:
            await message.answer(w)


async def check_spending_limit_warnings(db: Database, user_id: int) -> list[str]:
    warnings: list[str] = []
    weekly_limit = await db.get_weekly_limit(user_id=user_id)
    if weekly_limit and weekly_limit > 0:
        start, end = db.week_range()
        rows = await db.expenses_between(user_id, start, end)
        week_expense = sum(
            int(r["amount"]) for r in rows if r.get("type", "expense") == "expense"
        )
        remaining = weekly_limit - week_expense
        pct = (week_expense / weekly_limit) * 100
        pct_int = int(round(pct))

        if pct >= 100:
            warnings.append(
                f"🚨 <b>Diqqat! Haftalik limit oshib ketdi!</b> ({pct_int}%)\n"
                f"Sarflangan: <b>{format_money(week_expense)} so'm</b> / {format_money(weekly_limit)} so'm\n"
                f"Oshiqcha: <b>{format_money(abs(remaining))} so'm</b>"
            )
        elif pct >= 80:
            warnings.append(
                f"⚠️ <b>Haftalik limitga yaqinlashdingiz!</b> ({pct_int}%)\n"
                f"Qoldiq: <b>{format_money(remaining)} so'm</b> (Sarflangan: {format_money(week_expense)} / {format_money(weekly_limit)} so'm)"
            )
        else:
            warnings.append(
                f"📊 Haftalik qoldiq: <b>{format_money(remaining)} so'm</b> ({format_money(week_expense)} / {format_money(weekly_limit)} so'm)"
            )
    return warnings


def _render_report(
    title: str,
    rows: list[dict[str, Any]],
    weekly_limit: int | None = None,
) -> str:
    income = sum(int(r["amount"]) for r in rows if r.get("type", "expense") == "income")
    expense = sum(int(r["amount"]) for r in rows if r.get("type", "expense") == "expense")
    balance = income - expense

    lines = [
        f"<b>{title}</b>",
        f"💰 Kirim: <b>{format_money(income)} so'm</b>",
        f"💸 Xarajat: <b>{format_money(expense)} so'm</b>",
    ]

    if weekly_limit and weekly_limit > 0:
        remaining = weekly_limit - expense
        pct = round((expense / weekly_limit) * 100) if weekly_limit else 0
        lines.append(f"📌 Haftalik pul: <b>{format_money(weekly_limit)} so'm</b>")
        lines.append(f"📊 Haftalik qoldiq: <b>{format_money(remaining)} so'm</b> ({pct}% sarflandi)")
    else:
        lines.append(f"📊 Balans: <b>{format_money(balance)} so'm</b>")

    if rows:
        lines.append("\n<b>Yozuvlar:</b>")
        for r in rows:
            tx_type = r.get("type", "expense")
            sign = "+" if tx_type == "income" else "-"
            icon = "💰" if tx_type == "income" else "💸"
            desc = r.get("description") or ""
            desc_str = f" — {desc}" if desc else ""
            lines.append(f"{icon} {sign}{format_money(r['amount'])} so'm{desc_str}")

    return "\n".join(lines)
