"""Command, callback, and free-text expense handlers."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from bot.db import Database
from bot.parser import format_money, guess_category, parse_expense

log = logging.getLogger(__name__)
router = Router()


class ExpenseStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_new_category = State()
    waiting_for_delete_category = State()


class OwnerOnlyMiddleware(BaseMiddleware):
    """Reject anyone who is not the configured Telegram user."""

    def __init__(self, db: Database, allowed_user_id: int) -> None:
        self.db = db
        self.allowed_user_id = allowed_user_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id != self.allowed_user_id:
            if isinstance(event, Message):
                await event.answer("This bot is private.")
            return None
        data["db"] = self.db
        return await handler(event, data)


def setup_router(db: Database, allowed_user_id: int) -> Router:
    middleware = OwnerOnlyMiddleware(db, allowed_user_id)
    router.message.outer_middleware(middleware)
    router.callback_query.outer_middleware(middleware)
    return router


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Xarajatlaringizni shu yerga yozib boring.\n\n"
        "Just send a message like:\n"
        "• <code>30000 taksi</code>\n"
        "• <code>150k ovqatga ketdi</code>\n"
        "• <code>sotib oldim kiyim 200000</code>\n\n"
        "Commands:\n"
        "/today — today's total\n"
        "/week — this week\n"
        "/month — this month\n"
        "/categories — view or edit categories\n"
        "/delete_last — undo the last expense"
    )


@router.message(Command("today"))
async def cmd_today(message: Message, db: Database) -> None:
    start, end = db.day_range()
    rows = await db.expenses_between(message.from_user.id, start, end)
    emojis = await db.emoji_map()
    await message.answer(_render_report("Today", rows, emojis))


@router.message(Command("week"))
async def cmd_week(message: Message, db: Database) -> None:
    start, end = db.week_range()
    rows = await db.expenses_between(message.from_user.id, start, end)
    emojis = await db.emoji_map()
    await message.answer(_render_report("This week", rows, emojis))


@router.message(Command("month"))
async def cmd_month(message: Message, db: Database) -> None:
    start, end = db.month_range()
    rows = await db.expenses_between(message.from_user.id, start, end)
    emojis = await db.emoji_map()
    await message.answer(_render_report("This month", rows, emojis))


@router.message(Command("delete_last"))
async def cmd_delete_last(message: Message, db: Database) -> None:
    deleted = await db.delete_last(message.from_user.id)
    if not deleted:
        await message.answer("Nothing to delete — no expenses logged yet.")
        return
    desc = f" ({deleted['description']})" if deleted.get("description") else ""
    await message.answer(
        f"Removed: {format_money(deleted['amount'])} so'm — {deleted['category']}{desc}"
    )


@router.message(Command("categories"))
async def cmd_categories(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        await _categories_text(db),
        reply_markup=_categories_keyboard(),
    )


@router.callback_query(F.data == "cat:add")
async def cb_add_category(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ExpenseStates.waiting_for_new_category)
    await callback.message.answer(
        "Send a new category in this format:\n"
        "<code>Name | emoji | keyword1, keyword2</code>\n\n"
        "Example:\n"
        "<code>Health | 💊 | dori, apteka, shifokor</code>"
    )
    await callback.answer()


@router.callback_query(F.data == "cat:delete")
async def cb_delete_category(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    cats = await db.list_categories()
    buttons = [
        [InlineKeyboardButton(text=f"{c['emoji']} {c['name']}", callback_data=f"catdel:{c['name']}")]
        for c in cats
    ]
    buttons.append([InlineKeyboardButton(text="Cancel", callback_data="cat:cancel")])
    await state.set_state(ExpenseStates.waiting_for_delete_category)
    await callback.message.answer("Which category should I remove?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data == "cat:cancel")
async def cb_cancel_category(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Cancelled.")
    await callback.answer()


@router.callback_query(F.data.startswith("catdel:"))
async def cb_confirm_delete_category(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    name = callback.data.split(":", 1)[1]
    if name in {"Food", "Transport", "Clothing", "Utilities", "Rent", "Other"}:
        await callback.answer("Built-in categories can't be deleted. You can still add keywords.", show_alert=True)
        return
    ok = await db.delete_category(name)
    await state.clear()
    if ok:
        await callback.message.answer(f"Removed category: {name}")
    else:
        await callback.message.answer("That category was not found.")
    await callback.answer()


@router.message(ExpenseStates.waiting_for_new_category)
async def on_new_category(message: Message, db: Database, state: FSMContext) -> None:
    if not message.text:
        return
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) < 1 or not parts[0]:
        await message.answer("Please send: <code>Name | emoji | keywords</code>")
        return
    name = parts[0]
    emoji = parts[1] if len(parts) > 1 and parts[1] else "📌"
    keywords = parts[2] if len(parts) > 2 else name.lower()
    await db.add_category(name, emoji, keywords)
    await state.clear()
    await message.answer(f"Saved category {emoji} {name}.", reply_markup=_categories_keyboard())


@router.callback_query(F.data.startswith("pickcat:"))
async def cb_pick_category(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    data = await state.get_data()
    amount = data.get("amount")
    description = data.get("description") or ""
    if amount is None:
        await callback.answer("That draft expired. Send the expense again.", show_alert=True)
        await state.clear()
        return
    category = callback.data.split(":", 1)[1]
    await db.add_expense(callback.from_user.id, int(amount), category, description or None)
    await state.clear()
    extra = f"\n{description}" if description else ""
    await callback.message.edit_text(
        f"Logged {format_money(int(amount))} so'm → {category}{extra}"
    )
    await callback.answer()


@router.message(F.text)
async def on_text(message: Message, db: Database, state: FSMContext) -> None:
    """Treat any non-command text as a possible expense."""
    text = message.text or ""
    if text.startswith("/"):
        return

    current = await state.get_state()
    if current == ExpenseStates.waiting_for_category.state:
        extra = await db.extra_keywords()
        category = guess_category(text, extra)
        data = await state.get_data()
        amount = data.get("amount")
        description = data.get("description") or text
        if category and amount is not None:
            await db.add_expense(message.from_user.id, int(amount), category, description)
            await state.clear()
            await message.answer(f"Logged {format_money(int(amount))} so'm → {category}")
            return
        await message.answer("Please tap a category button, or send a word I know.")
        return

    extra = await db.extra_keywords()
    parsed = parse_expense(text, extra)
    if parsed is None:
        await message.answer(
            "I couldn't find an amount. Try:\n"
            "<code>15000 taksi</code> or <code>150k ovqat</code>"
        )
        return

    if parsed.category:
        await db.add_expense(
            message.from_user.id,
            parsed.amount,
            parsed.category,
            parsed.description or None,
        )
        note = f" — {parsed.description}" if parsed.description else ""
        await message.answer(
            f"Logged {format_money(parsed.amount)} so'm → {parsed.category}{note}"
        )
        return

    await state.set_state(ExpenseStates.waiting_for_category)
    await state.update_data(amount=parsed.amount, description=parsed.description)
    cats = await db.list_categories()
    await message.answer(
        f"Got {format_money(parsed.amount)} so'm. Which category?",
        reply_markup=_category_picker(cats),
    )


def _category_picker(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for cat in categories:
        row.append(
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"pickcat:{cat['name']}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _categories_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Add", callback_data="cat:add"),
                InlineKeyboardButton(text="🗑 Delete", callback_data="cat:delete"),
            ]
        ]
    )


async def _categories_text(db: Database) -> str:
    cats = await db.list_categories()
    lines = ["Categories:"]
    for cat in cats:
        kws = cat["keywords"].replace(",", ", ") if cat["keywords"] else "—"
        lines.append(f"{cat['emoji']} <b>{cat['name']}</b>\n<code>{kws}</code>")
    lines.append("\nAdd a category with extra keywords so I can auto-detect them.")
    return "\n\n".join(lines)


def _render_report(title: str, rows: list[dict[str, Any]], emojis: dict[str, str]) -> str:
    if not rows:
        return f"<b>{title}</b>\nNo expenses yet."

    total = sum(int(r["amount"]) for r in rows)
    buckets: dict[str, int] = defaultdict(int)
    for row in rows:
        buckets[row["category"]] += int(row["amount"])

    ranked = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    lines = [
        f"<b>{title}</b>",
        f"Total: <b>{format_money(total)} so'm</b>",
        "",
    ]
    for name, amount in ranked:
        pct = round(amount * 100 / total) if total else 0
        emoji = emojis.get(name, "📌")
        lines.append(f"{emoji} {name}: {format_money(amount)} so'm ({pct}%)")
    return "\n".join(lines)
