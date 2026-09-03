"""Command, free-text, voice, photo receipt, and callback handlers for FinMate Bot."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from bot.ai_service import (
    get_financial_advice,
    ocr_receipt_image,
    parse_text_with_gemini,
    transcribe_and_parse_audio,
)
from bot.chart import generate_category_pie_chart
from bot.config import Settings
from bot.db import Database
from bot.export import generate_excel_export
from bot.parser import format_money, parse_expense

log = logging.getLogger(__name__)
router = Router()


class AppMiddleware(BaseMiddleware):
    """Inject database and settings into event handler data."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["settings"] = self.settings
        return await handler(event, data)


def setup_router(db: Database, settings: Settings) -> Router:
    middleware = AppMiddleware(db, settings)
    router.message.outer_middleware(middleware)
    router.callback_query.outer_middleware(middleware)
    return router


def render_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░" * length + " 0%"
    ratio = min(max(current / total, 0.0), 1.0)
    filled = int(round(ratio * length))
    bar = "▓" * filled + "░" * (length - filled)
    return f"{bar} {int(round(ratio * 100))}%"


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>FinMate Bot'ga xush kelibsiz!</b>\n"
        "Shaxsiy moliya va byudjetingizni aqlli nazorat qiluvchi yordamchingiz. 💸\n\n"
        "✨ <b>Asosiy Imkoniyatlar:</b>\n"
        "1️⃣ <b>Erkin matn va NLP:</b> <code>\"kofega 15000 ketdi\"</code> yoki <code>\"+3 mln maosh\"</code>\n"
        "2️⃣ <b>Ovozli xabar:</b> Ovozli xabar yuboring, Gemini uni tushunadi 🎙\n"
        "3️⃣ <b>Chek rasmi OCR:</b> Chek fotosini yuboring, avto-hisoblaymiz 🧾\n"
        "4️⃣ <b>Byudjet va Limitlar:</b> <code>/limit</code> va <code>/set_weekly_money</code>\n"
        "5️⃣ <b>Jamg'arma Maqsadlari:</b> <code>/maqsad</code> va <code>/maqsad_yangi</code>\n"
        "6️⃣ <b>Statistika va Diagrammalar:</b> <code>/stats</code>, <code>/week</code>, <code>/month</code>\n"
        "7️⃣ <b>Takroriy Xarajatlar:</b> <code>/takroriy</code>\n"
        "8️⃣ <b>AI Maslahatchi:</b> <code>/maslahat [savolingiz]</code>\n"
        "9️⃣ <b>Excel Export:</b> <code>/export</code>\n"
        "🔟 <b>Balans:</b> <code>/balans</code>\n"
    )


# --- 11. Daromad va Balans ---
@router.message(Command("balans", "balance"))
async def cmd_balance(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    totals = await db.all_time_totals(user_id)
    income = totals.get("income", 0)
    expense = totals.get("expense", 0)
    balance = income - expense

    await message.answer(
        f"📊 <b>Umumiy Balans Holati:</b>\n\n"
        f"💰 Jami daromad: <b>{format_money(income)} so'm</b>\n"
        f"💸 Jami xarajat: <b>{format_money(expense)} so'm</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💵 Sof Balans: <b>{format_money(balance)} so'm</b>"
    )


@router.message(Command("daromad", "income"))
async def cmd_income(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Daromad kiritish uchun: <code>/daromad 3000000 Maosh</code>")
        return

    parsed = parse_expense(args[1])
    if parsed is None or parsed.amount <= 0:
        await message.answer("Noto'g'ri summa kiritildi. Masalan: <code>/daromad 3000000 Maosh</code>")
        return

    description = args[2] if len(args) > 2 else "Daromad"
    user_id = message.from_user.id if message.from_user else 0
    await db.add_expense(user_id, parsed.amount, "Kirim", description, type="income")

    await message.answer(f"💰 Kirim saqlandi: <b>+{format_money(parsed.amount)} so'm</b> ({description})")


# --- 4. Byudjet va Limitlar ---
@router.message(Command("set_weekly_money", "set_weekly_limit"))
async def cmd_set_weekly_money(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Haftalik limit belgilash: <code>/set_weekly_money 300k</code>")
        return
    parsed = parse_expense(args[1])
    if parsed is None or parsed.amount <= 0:
        await message.answer("Noto'g'ri summa kiritildi.")
        return
    user_id = message.from_user.id if message.from_user else 0
    await db.set_weekly_limit(parsed.amount, user_id=user_id)
    await message.answer(f"✅ Haftalik limit o'rnatildi: <b>{format_money(parsed.amount)} so'm</b>")


@router.message(Command("limit"))
async def cmd_category_limit(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=2)
    user_id = message.from_user.id if message.from_user else 0

    if len(args) < 3:
        budgets = await db.get_category_budgets(user_id)
        if not budgets:
            await message.answer(
                "📌 <b>Kategoriya bo'yicha limitlar o'rnatilmagan.</b>\n"
                "Limit o'rnatish uchun: <code>/limit Transport 300k</code>"
            )
            return
        lines = ["📌 <b>Oylik Kategoriya Limitlari:</b>\n"]
        start, end = db.month_range()
        rows = await db.expenses_between(user_id, start, end)
        curr_expenses: dict[str, int] = {}
        for r in rows:
            if r.get("type", "expense") == "expense":
                c = r["category"]
                curr_expenses[c] = curr_expenses.get(c, 0) + int(r["amount"])

        for cat, lim in budgets.items():
            spent = curr_expenses.get(cat, 0)
            bar = render_progress_bar(spent, lim)
            lines.append(f"• <b>{cat}:</b> {format_money(spent)} / {format_money(lim)} so'm\n  {bar}")
        await message.answer("\n".join(lines))
        return

    cat_name = args[1].capitalize()
    parsed = parse_expense(args[2])
    if parsed is None or parsed.amount <= 0:
        await message.answer("Noto'g'ri summa kiritildi. Masalan: <code>/limit Transport 300k</code>")
        return

    await db.set_category_limit(user_id, cat_name, parsed.amount)
    await message.answer(f"✅ <b>{cat_name}</b> uchun oylik limit o'rnatildi: <b>{format_money(parsed.amount)} so'm</b>")


@router.message(Command("kunlik_maqsad", "daily_target"))
async def cmd_daily_target(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=1)
    user_id = message.from_user.id if message.from_user else 0
    if len(args) < 2:
        target = await db.get_daily_target(user_id)
        if target:
            await message.answer(f"🎯 Kunlik xarajat maqsadingiz: <b>{format_money(target)} so'm</b>")
        else:
            await message.answer("Kunlik maqsad o'rnatish uchun: <code>/kunlik_maqsad 50k</code>")
        return

    parsed = parse_expense(args[1])
    if parsed is None or parsed.amount <= 0:
        await message.answer("Noto'g'ri summa.")
        return

    await db.set_daily_target(user_id, parsed.amount)
    await message.answer(f"🎯 Kunlik xarajat maqsadi o'rnatildi: <b>{format_money(parsed.amount)} so'm</b>")


# --- 5. Jamg'arma Maqsadlari ---
@router.message(Command("maqsad_yangi", "new_goal"))
async def cmd_new_goal(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Yangi maqsad yaratish: <code>/maqsad_yangi Telefon 3000000</code>")
        return

    title = args[1]
    parsed = parse_expense(args[2])
    if parsed is None or parsed.amount <= 0:
        await message.answer("Noto'g'ri summa kiritildi.")
        return

    user_id = message.from_user.id if message.from_user else 0
    goal_id = await db.add_savings_goal(user_id, title, parsed.amount)
    await message.answer(
        f"🎯 <b>Yangi jamg'arma maqsadi yaratildi!</b> (ID: {goal_id})\n"
        f"📌 Maqsad: <b>{title}</b>\n"
        f"💰 Kerakli summa: <b>{format_money(parsed.amount)} so'm</b>\n\n"
        f"Pul qo'shish uchun: <code>/toplash {goal_id} 100k</code>"
    )


@router.message(Command("maqsad", "goals"))
async def cmd_goals(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    goals = await db.list_savings_goals(user_id)
    if not goals:
        await message.answer(
            "🎯 <b>Jamg'arma maqsadlari mavjud emas.</b>\n"
            "Yaratish uchun: <code>/maqsad_yangi Telefon 3000000</code>"
        )
        return

    lines = ["🎯 <b>Jamg'arma Maqsadlaringiz:</b>\n"]
    for g in goals:
        bar = render_progress_bar(g["current_amount"], g["target_amount"])
        lines.append(
            f"🆔 <b>{g['id']}. {g['title']}</b>\n"
            f"💰 {format_money(g['current_amount'])} / {format_money(g['target_amount'])} so'm\n"
            f"📊 {bar}\n"
        )
    lines.append("Pul qo'shish: <code>/toplash [ID] [Summa]</code>")
    await message.answer("\n".join(lines))


@router.message(Command("toplash", "deposit"))
async def cmd_deposit_goal(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3 or not args[1].isdigit():
        await message.answer("Jamg'armaga pul qo'shish: <code>/toplash 1 100k</code>")
        return

    goal_id = int(args[1])
    parsed = parse_expense(args[2])
    if parsed is None or parsed.amount <= 0:
        await message.answer("Noto'g'ri summa.")
        return

    user_id = message.from_user.id if message.from_user else 0
    updated = await db.deposit_savings_goal(goal_id, user_id, parsed.amount)
    if not updated:
        await message.answer("❌ Maqsad topilmadi.")
        return

    bar = render_progress_bar(updated["current_amount"], updated["target_amount"])
    await message.answer(
        f"✅ <b>{updated['title']}</b> maqsadiga +<b>{format_money(parsed.amount)} so'm</b> qo'shildi!\n"
        f"💰 Jami yig'ildi: {format_money(updated['current_amount'])} / {format_money(updated['target_amount'])} so'm\n"
        f"📊 Progress: {bar}"
    )


# --- 7. Takroriy Xarajatlar ---
@router.message(Command("takroriy", "recurring"))
async def cmd_recurring(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    saved = await db.list_recurring_expenses(user_id)
    candidates = await db.detect_recurring_candidates(user_id)

    lines = []
    if saved:
        lines.append("🔄 <b>Kuzatilayotgan takroriy xarajatlar (Obunalar):</b>")
        for s in saved:
            lines.append(f"• <b>{s['title']}</b> — {format_money(s['amount'])} so'm ({s['category']})")
        lines.append("")

    if candidates:
        lines.append("💡 <b>Aniqlangan potentsial obunalar:</b>")
        for c in candidates:
            desc = c['description'] or c['category']
            lines.append(f"• <b>{desc}</b> ({format_money(c['amount'])} so'm, {c['cnt']} marta takrorlangan)")
        lines.append("\nKuzatuvga qo'shish uchun: <code>/takroriy_qush Netflix 50000 Ko'ngilochar</code>")

    if not lines:
        lines.append("🔄 Takrorlanuvchi xarajatlar topilmadi.")

    await message.answer("\n".join(lines))


@router.message(Command("takroriy_qush", "add_recurring"))
async def cmd_add_recurring(message: Message, db: Database) -> None:
    args = (message.text or "").split(maxsplit=3)
    if len(args) < 3:
        await message.answer("Takroriy xarajat qo'shish: <code>/takroriy_qush Netflix 50k Ko'ngilochar</code>")
        return

    title = args[1]
    parsed = parse_expense(args[2])
    category = args[3].capitalize() if len(args) > 3 else "Boshqa"

    if parsed is None or parsed.amount <= 0:
        await message.answer("Noto'g'ri summa.")
        return

    user_id = message.from_user.id if message.from_user else 0
    await db.add_recurring_expense(user_id, title, parsed.amount, category)
    await message.answer(f"✅ Takroriy xarajat saqlandi: <b>{title}</b> — {format_money(parsed.amount)} so'm")


# --- 8. Moliyaviy Maslahatchi Rejimi ---
@router.message(Command("maslahat", "advice"))
async def cmd_advice(message: Message, db: Database, settings: Settings) -> None:
    question = (message.text or "").replace("/maslahat", "").replace("/advice", "").strip()
    if not question:
        question = "Mening xarajatlarimni tahlil qilib, qayerdan tejashim mumkinligi haqida maslahat bering."

    user_id = message.from_user.id if message.from_user else 0
    start, end = db.month_range()
    rows = await db.expenses_between(user_id, start, end)
    income_total = sum(int(r["amount"]) for r in rows if r.get("type") == "income")
    expense_total = sum(int(r["amount"]) for r in rows if r.get("type") == "expense")
    cat_totals = await db.get_category_totals(user_id, start, end)

    context_lines = [
        f"Ushbu oy jami kirim: {income_total} so'm",
        f"Ushbu oy jami xarajat: {expense_total} so'm",
        "Kategoriyalar bo'yicha sarf:",
    ]
    for cat, amt in cat_totals.items():
        context_lines.append(f"- {cat}: {amt} so'm")

    user_context = "\n".join(context_lines)
    await message.answer("💡 <i>Moliyaviy ma'lumotlaringiz tahlil qilinmoqda, kuting...</i>")

    advice = get_financial_advice(settings.gemini_api_key, user_context, question)
    await message.answer(f"🤖 <b>AI Moliyaviy Maslahatchi:</b>\n\n{advice}")


# --- 10. Export ---
@router.message(Command("export"))
async def cmd_export(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    txs = await db.get_all_transactions(user_id)
    if not txs:
        await message.answer("Export qilish uchun hech qanday xarajatlar topilmadi.")
        return

    excel_bytes = generate_excel_export(txs)
    input_file = BufferedInputFile(excel_bytes, filename="FinMate_xarajatlar.xlsx")
    await message.answer_document(input_file, caption="📊 Barcha xarajat va kirimlaringiz Excel fayli.")


# --- 6. Statistika va Hisobotlar ---
@router.message(Command("stats", "hisobot"))
async def cmd_stats(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    start, end = db.month_range()
    rows = await db.expenses_between(user_id, start, end)
    cat_totals = await db.get_category_totals(user_id, start, end)
    top_info = await db.get_top_spending_info(user_id, start, end)
    comp = await db.get_month_comparison(user_id)

    lines = ["📊 <b>Oylik Statistika va Tahlil:</b>\n"]
    if top_info["top_category"]:
        lines.append(f"🏆 Eng ko'p sarflangan kategoriya: <b>{top_info['top_category']}</b> ({format_money(top_info['top_category_amount'])} so'm)")
    if top_info["top_day"]:
        lines.append(f"📅 Eng ko me'yordan oshgan kun: <b>{top_info['top_day']}</b> ({format_money(top_info['top_day_amount'])} so'm)")

    diff_pct = comp["diff_percent"]
    if diff_pct != 0:
        sign = "+" if diff_pct > 0 else ""
        lines.append(f"📈 O'tgan oyga nisbatan: <b>{sign}{diff_pct:.1f}%</b> xarajat qildingiz.")

    caption = "\n".join(lines)
    chart_bytes = generate_category_pie_chart(cat_totals, title="Oylik Xarajatlar Diagrammasi")

    if chart_bytes:
        photo = BufferedInputFile(chart_bytes, filename="chart.png")
        await message.answer_photo(photo, caption=caption)
    else:
        await message.answer(caption)


@router.message(Command("today"))
async def cmd_today(message: Message, db: Database) -> None:
    user_id = message.from_user.id if message.from_user else 0
    start, end = db.day_range()
    rows = await db.expenses_between(user_id, start, end)
    weekly_limit = await db.get_weekly_limit(user_id=user_id)
    daily_target = await db.get_daily_target(user_id)

    text = _render_report("Bugungi hisobot", rows, weekly_limit=weekly_limit)
    if daily_target:
        today_expense = sum(int(r["amount"]) for r in rows if r.get("type") == "expense")
        bar = render_progress_bar(today_expense, daily_target)
        text += f"\n🎯 Kunlik maqsad: {format_money(today_expense)} / {format_money(daily_target)} so'm\n{bar}"
    await message.answer(text)


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
    cat_totals = await db.get_category_totals(user_id, start, end)
    text = _render_report("Bu oylik hisobot", rows)

    chart_bytes = generate_category_pie_chart(cat_totals)
    if chart_bytes:
        photo = BufferedInputFile(chart_bytes, filename="month_chart.png")
        await message.answer_photo(photo, caption=text)
    else:
        await message.answer(text)


# --- 2. Voice Input Handler ---
@router.message(F.voice)
async def on_voice(message: Message, db: Database, settings: Settings) -> None:
    if not message.voice:
        return

    await message.answer("🎙 <i>Ovozli xabaringiz tahlil qilinmoqda...</i>")
    bot = message.bot
    if not bot:
        return

    file = await bot.get_file(message.voice.file_id)
    if not file.file_path:
        await message.answer("Ovozli faylni yuklab bo'lmadi.")
        return

    file_bytes_io = await bot.download_file(file.file_path)
    file_bytes = file_bytes_io.read()

    categories = [c["name"] for c in await db.list_categories()]
    parsed = transcribe_and_parse_audio(
        api_key=settings.gemini_api_key,
        audio_bytes=file_bytes,
        mime_type="audio/ogg",
        categories=categories,
    )

    if not parsed or not parsed.get("amount"):
        await message.answer("🎙 Ovozli xabardan summa aniqlanmadi. Qayta urinib ko'ring yoki yozib kiriting.")
        return

    user_id = message.from_user.id if message.from_user else 0
    amount = parsed["amount"]
    category = parsed["category"]
    description = parsed["description"] or parsed.get("transcript") or "Ovozli kiritish"
    tx_type = parsed["type"]

    await db.add_expense(user_id, amount, category, description, type=tx_type)

    sign = "+" if tx_type == "income" else "-"
    icon = "💰 Kirim" if tx_type == "income" else "💸 Xarajat"
    transcript_str = f"\n🗣 <i>Transkript: \"{parsed.get('transcript', '')}\"</i>" if parsed.get('transcript') else ""

    await message.answer(
        f"{icon} saqlandi: <b>{sign}{format_money(amount)} so'm</b>\n"
        f"🏷 Kategoriya: <b>{category}</b> ({description}){transcript_str}"
    )

    if tx_type == "expense":
        warnings = await check_spending_limit_warnings(db, user_id, category)
        for w in warnings:
            await message.answer(w)


# --- 3. Receipt Photo OCR Handler ---
@router.message(F.photo)
async def on_photo(message: Message, db: Database, settings: Settings) -> None:
    if not message.photo:
        return

    await message.answer("🧾 <i>Chek rasmi OCR tahlil qilinmoqda...</i>")
    bot = message.bot
    if not bot:
        return

    photo = message.photo[-1]  # Highest resolution
    file = await bot.get_file(photo.file_id)
    if not file.file_path:
        await message.answer("Chek rasmini yuklab bo'lmadi.")
        return

    file_bytes_io = await bot.download_file(file.file_path)
    file_bytes = file_bytes_io.read()

    categories = [c["name"] for c in await db.list_categories()]
    parsed = ocr_receipt_image(
        api_key=settings.gemini_api_key,
        image_bytes=file_bytes,
        mime_type="image/jpeg",
        categories=categories,
    )

    if not parsed or not parsed.get("amount"):
        await message.answer("🧾 Chek rasmidan summa aniqlanmadi.")
        return

    amount = parsed["amount"]
    store = parsed.get("store", "Do'kon")
    category = parsed.get("category", "Xarid")

    # Inline Keyboard for confirmation
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Saqlash", callback_data=f"save_receipt:{amount}:{category}:{store[:15]}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_receipt"),
            ]
        ]
    )

    await message.answer(
        f"🧾 <b>Chek aniqlandi:</b>\n\n"
        f"🏬 Do'kon / Tashkilot: <b>{store}</b>\n"
        f"💰 Jami summa: <b>{format_money(amount)} so'm</b>\n"
        f"🏷 Kategoriya: <b>{category}</b>\n\n"
        f"Xarajat sifatiga saqlashni tasdiqlaysizmi?",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("save_receipt:"))
async def on_confirm_receipt(query: CallbackQuery, db: Database) -> None:
    if not query.data or not query.message:
        return

    parts = query.data.split(":", 3)
    if len(parts) < 4:
        return

    amount = int(parts[1])
    category = parts[2]
    store = parts[3]

    user_id = query.from_user.id
    await db.add_expense(user_id, amount, category, f"Chek: {store}", type="expense")

    await query.message.edit_text(
        f"✅ Chek xarajat sifatiga saqlandi!\n"
        f"💸 Summa: <b>{format_money(amount)} so'm</b> ({category})"
    )
    await query.answer("Saqlandi")

    warnings = await check_spending_limit_warnings(db, user_id, category)
    for w in warnings:
        await query.message.answer(w)


@router.callback_query(F.data == "cancel_receipt")
async def on_cancel_receipt(query: CallbackQuery) -> None:
    if query.message:
        await query.message.edit_text("❌ Chekni saqlash bekor qilindi.")
    await query.answer("Bekor qilindi")


# --- 1. NLP & Fallback Free-text Handler ---
@router.message(F.text)
async def on_text(message: Message, db: Database, settings: Settings) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    categories = [c["name"] for c in await db.list_categories()]

    # 1. Try Gemini NLP first if API key is provided
    parsed_dict = None
    if settings.gemini_api_key:
        parsed_dict = parse_text_with_gemini(settings.gemini_api_key, text, categories)

    if parsed_dict and parsed_dict.get("amount"):
        amount = parsed_dict["amount"]
        category = parsed_dict["category"]
        description = parsed_dict["description"] or text
        tx_type = parsed_dict["type"]
    else:
        # Fallback to local regex parser
        parsed = parse_expense(text)
        if parsed is None:
            await message.answer(
                "Summani aniqlay olmadim. Masalan:\n"
                "<code>kofega 15000 ketdi</code> yoki <code>+3000000 maosh</code>"
            )
            return
        amount = parsed.amount
        category = parsed.category or ("Kirim" if parsed.type == "income" else "Xarajat")
        description = parsed.description or text
        tx_type = parsed.type

    user_id = message.from_user.id if message.from_user else 0
    await db.add_expense(user_id, amount, category, description, type=tx_type)

    desc_str = f" ({description})" if description and description != str(amount) else ""

    if tx_type == "income":
        await message.answer(f"💰 Kirim saqlandi: <b>+{format_money(amount)} so'm</b>{desc_str}")
    else:
        await message.answer(f"💸 Xarajat saqlandi: <b>{format_money(amount)} so'm</b>{desc_str}")
        warnings = await check_spending_limit_warnings(db, user_id, category)
        for w in warnings:
            await message.answer(w)


async def check_spending_limit_warnings(db: Database, user_id: int, category: str | None = None) -> list[str]:
    warnings: list[str] = []

    # Weekly limit warning
    weekly_limit = await db.get_weekly_limit(user_id=user_id)
    if weekly_limit and weekly_limit > 0:
        start, end = db.week_range()
        rows = await db.expenses_between(user_id, start, end)
        week_expense = sum(int(r["amount"]) for r in rows if r.get("type", "expense") == "expense")
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
                f"Qoldiq: <b>{format_money(remaining)} so'm</b> ({format_money(week_expense)} / {format_money(weekly_limit)} so'm)"
            )

    # Category budget limit warning
    if category:
        cat_budget = await db.get_category_budget(user_id, category)
        if cat_budget and cat_budget > 0:
            m_start, m_end = db.month_range()
            m_rows = await db.expenses_between(user_id, m_start, m_end)
            cat_spent = sum(int(r["amount"]) for r in m_rows if r.get("type", "expense") == "expense" and r.get("category") == category)
            cat_pct = (cat_spent / cat_budget) * 100
            if cat_pct >= 100:
                warnings.append(
                    f"🚨 <b>{category} bo'yicha oylik limit oshib ketdi!</b> ({int(cat_pct)}%)\n"
                    f"Sarflangan: <b>{format_money(cat_spent)} so'm</b> / {format_money(cat_budget)} so'm"
                )
            elif cat_pct >= 80:
                warnings.append(
                    f"⚠️ <b>{category} bo'yicha limitga yaqinlashdingiz!</b> ({int(cat_pct)}%)\n"
                    f"Sarflangan: <b>{format_money(cat_spent)} so'm</b> / {format_money(cat_budget)} so'm"
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
            lines.append(f"{icon} {sign}{format_money(r['amount'])} so'm ({r.get('category', 'Boshqa')}){desc_str}")

    return "\n".join(lines)
