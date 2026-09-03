"""SQLite helpers for expenses and custom categories."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bot.parser import DEFAULT_CATEGORIES

# Timestamps are stored as UTC ISO-8601. Range queries convert local days first.
_CREATE_EXPENSES = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'expense'
);
"""

_CREATE_CATEGORIES = """
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY,
    emoji TEXT NOT NULL DEFAULT '📌',
    keywords TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_CREATE_CATEGORY_BUDGETS = """

CREATE TABLE IF NOT EXISTS category_budgets (
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    monthly_limit INTEGER NOT NULL,
    PRIMARY KEY (user_id, category)
);
"""

_CREATE_SAVINGS_GOALS = """
CREATE TABLE IF NOT EXISTS savings_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    target_amount INTEGER NOT NULL,
    current_amount INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

_CREATE_RECURRING_EXPENSES = """
CREATE TABLE IF NOT EXISTS recurring_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    amount INTEGER NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path, timezone: str = "Asia/Tashkent") -> None:
        self.path = path
        self.tz = ZoneInfo(timezone)

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._init_sync)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_EXPENSES)
            conn.execute(_CREATE_CATEGORIES)
            conn.execute(_CREATE_SETTINGS)
            conn.execute(_CREATE_CATEGORY_BUDGETS)
            conn.execute(_CREATE_SAVINGS_GOALS)
            conn.execute(_CREATE_RECURRING_EXPENSES)

            # Migration: Ensure 'type' column exists in existing expenses table
            cursor = conn.execute("PRAGMA table_info(expenses)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "type" not in columns:
                conn.execute(
                    "ALTER TABLE expenses ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'"
                )

            for name, data in DEFAULT_CATEGORIES.items():
                keywords = ",".join(data["keywords"])  # type: ignore[arg-type]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO categories (name, emoji, keywords)
                    VALUES (?, ?, ?)
                    """,
                    (name, data["emoji"], keywords),
                )
            conn.commit()


    async def add_expense(
        self,
        user_id: int,
        amount: int,
        category: str,
        description: str | None,
        type: str = "expense",
    ) -> int:
        return await asyncio.to_thread(
            self._add_expense_sync, user_id, amount, category, description, type
        )

    def _add_expense_sync(
        self,
        user_id: int,
        amount: int,
        category: str,
        description: str | None,
        type: str = "expense",
    ) -> int:
        # Naive UTC string so SQLite datetime() comparisons stay reliable.
        created_at = datetime.now(tz=self.tz).astimezone(ZoneInfo("UTC")).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO expenses (user_id, amount, category, description, created_at, type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, amount, category, description or None, created_at, type),
            )
            conn.commit()
            return int(cur.lastrowid)

    async def delete_last(self, user_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._delete_last_sync, user_id)

    def _delete_last_sync(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, amount, category, description, created_at, type
                FROM expenses
                WHERE user_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM expenses WHERE id = ?", (row["id"],))
            conn.commit()
            return dict(row)

    async def has_expenses_today(self, user_id: int) -> bool:
        start, end = self.day_range()
        rows = await self.expenses_between(user_id, start, end)
        return bool(rows)

    async def expenses_between(
        self,
        user_id: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._expenses_between_sync, user_id, start_utc, end_utc
        )

    def _expenses_between_sync(
        self,
        user_id: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, amount, category, description, created_at, type
                FROM expenses
                WHERE user_id = ?
                  AND datetime(created_at) >= datetime(?)
                  AND datetime(created_at) < datetime(?)
                ORDER BY datetime(created_at) ASC
                """,
                (
                    user_id,
                    start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            ).fetchall()
            return [dict(r) for r in rows]

    async def all_time_totals(self, user_id: int) -> dict[str, int]:
        return await asyncio.to_thread(self._all_time_totals_sync, user_id)

    def _all_time_totals_sync(self, user_id: int) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT type, SUM(amount) as total
                FROM expenses
                WHERE user_id = ?
                GROUP BY type
                """,
                (user_id,),
            ).fetchall()
            totals = {"income": 0, "expense": 0}
            for row in rows:
                if row["type"] in totals:
                    totals[row["type"]] = int(row["total"] or 0)
            return totals

    async def get_setting(self, key: str) -> str | None:
        return await asyncio.to_thread(self._get_setting_sync, key)

    def _get_setting_sync(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._set_setting_sync, key, value)

    def _set_setting_sync(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    async def get_monthly_limit(self) -> int | None:
        val = await self.get_setting("monthly_limit")
        if val and val.isdigit():
            return int(val)
        return None

    async def set_monthly_limit(self, amount: int) -> None:
        await self.set_setting("monthly_limit", str(amount))

    async def get_weekly_limit(self, user_id: int | None = None) -> int | None:
        if user_id is not None:
            val = await self.get_setting(f"weekly_limit_{user_id}")
            if val and val.isdigit():
                return int(val)
        val = await self.get_setting("weekly_limit")
        if val and val.isdigit():
            return int(val)
        return None

    async def set_weekly_limit(self, amount: int, user_id: int | None = None) -> None:
        if user_id is not None:
            await self.set_setting(f"weekly_limit_{user_id}", str(amount))
        await self.set_setting("weekly_limit", str(amount))

    async def get_savings_goal(self) -> int | None:
        val = await self.get_setting("savings_goal")
        if val and val.isdigit():
            return int(val)
        return None

    async def set_savings_goal(self, amount: int) -> None:
        await self.set_setting("savings_goal", str(amount))

    async def list_categories(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_categories_sync)

    def _list_categories_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, emoji, keywords FROM categories ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]

    async def extra_keywords(self) -> dict[str, list[str]]:
        rows = await self.list_categories()
        mapping: dict[str, list[str]] = {}
        for row in rows:
            words = [w.strip() for w in (row["keywords"] or "").split(",") if w.strip()]
            mapping[row["name"]] = words
        return mapping

    async def emoji_map(self) -> dict[str, str]:
        rows = await self.list_categories()
        return {row["name"]: row["emoji"] for row in rows}

    async def add_category(self, name: str, emoji: str, keywords: str) -> None:
        await asyncio.to_thread(self._add_category_sync, name, emoji, keywords)

    def _add_category_sync(self, name: str, emoji: str, keywords: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO categories (name, emoji, keywords)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    emoji = excluded.emoji,
                    keywords = excluded.keywords
                """,
                (name, emoji, keywords),
            )
            conn.commit()

    async def delete_category(self, name: str) -> bool:
        return await asyncio.to_thread(self._delete_category_sync, name)

    def _delete_category_sync(self, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM categories WHERE name = ?", (name,))
            conn.commit()
            return cur.rowcount > 0

    async def set_category_limit(self, user_id: int, category: str, limit_amount: int) -> None:
        await asyncio.to_thread(self._set_category_limit_sync, user_id, category, limit_amount)

    def _set_category_limit_sync(self, user_id: int, category: str, limit_amount: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO category_budgets (user_id, category, monthly_limit)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit = excluded.monthly_limit
                """,
                (user_id, category, limit_amount),
            )
            conn.commit()

    async def get_category_budgets(self, user_id: int) -> dict[str, int]:
        return await asyncio.to_thread(self._get_category_budgets_sync, user_id)

    def _get_category_budgets_sync(self, user_id: int) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, monthly_limit FROM category_budgets WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return {row["category"]: int(row["monthly_limit"]) for row in rows}

    async def get_category_budget(self, user_id: int, category: str) -> int | None:
        budgets = await self.get_category_budgets(user_id)
        return budgets.get(category)

    async def set_daily_target(self, user_id: int, amount: int) -> None:
        await self.set_setting(f"daily_target_{user_id}", str(amount))

    async def get_daily_target(self, user_id: int) -> int | None:
        val = await self.get_setting(f"daily_target_{user_id}")
        if val and val.isdigit():
            return int(val)
        return None

    # --- Savings Goals ---
    async def add_savings_goal(self, user_id: int, title: str, target_amount: int) -> int:
        return await asyncio.to_thread(self._add_savings_goal_sync, user_id, title, target_amount)

    def _add_savings_goal_sync(self, user_id: int, title: str, target_amount: int) -> int:
        created_at = datetime.now(tz=self.tz).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO savings_goals (user_id, title, target_amount, current_amount, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (user_id, title, target_amount, created_at),
            )
            conn.commit()
            return int(cur.lastrowid)

    async def list_savings_goals(self, user_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_savings_goals_sync, user_id)

    def _list_savings_goals_sync(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, target_amount, current_amount, created_at
                FROM savings_goals
                WHERE user_id = ?
                ORDER BY id ASC
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    async def deposit_savings_goal(self, goal_id: int, user_id: int, amount: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._deposit_savings_goal_sync, goal_id, user_id, amount)

    def _deposit_savings_goal_sync(self, goal_id: int, user_id: int, amount: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, target_amount, current_amount FROM savings_goals WHERE id = ? AND user_id = ?",
                (goal_id, user_id),
            ).fetchone()
            if not row:
                return None
            new_amount = row["current_amount"] + amount
            conn.execute(
                "UPDATE savings_goals SET current_amount = ? WHERE id = ?",
                (new_amount, goal_id),
            )
            conn.commit()
            return {
                "id": goal_id,
                "title": row["title"],
                "target_amount": row["target_amount"],
                "current_amount": new_amount,
            }

    async def delete_savings_goal(self, goal_id: int, user_id: int) -> bool:
        return await asyncio.to_thread(self._delete_savings_goal_sync, goal_id, user_id)

    def _delete_savings_goal_sync(self, goal_id: int, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM savings_goals WHERE id = ? AND user_id = ?", (goal_id, user_id))
            conn.commit()
            return cur.rowcount > 0

    # --- Recurring Expenses ---
    async def add_recurring_expense(self, user_id: int, title: str, amount: int, category: str) -> int:
        return await asyncio.to_thread(self._add_recurring_expense_sync, user_id, title, amount, category)

    def _add_recurring_expense_sync(self, user_id: int, title: str, amount: int, category: str) -> int:
        created_at = datetime.now(tz=self.tz).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO recurring_expenses (user_id, title, amount, category, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, title, amount, category, created_at),
            )
            conn.commit()
            return int(cur.lastrowid)

    async def list_recurring_expenses(self, user_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_recurring_expenses_sync, user_id)

    def _list_recurring_expenses_sync(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, amount, category, created_at FROM recurring_expenses WHERE user_id = ? ORDER BY id ASC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    async def delete_recurring_expense(self, rec_id: int, user_id: int) -> bool:
        return await asyncio.to_thread(self._delete_recurring_expense_sync, rec_id, user_id)

    def _delete_recurring_expense_sync(self, rec_id: int, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, user_id))
            conn.commit()
            return cur.rowcount > 0

    async def detect_recurring_candidates(self, user_id: int) -> list[dict[str, Any]]:
        """Identify potential recurring expenses (same amount/category/description appearing 2+ times)."""
        return await asyncio.to_thread(self._detect_recurring_candidates_sync, user_id)

    def _detect_recurring_candidates_sync(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT amount, category, description, COUNT(*) as cnt
                FROM expenses
                WHERE user_id = ? AND type = 'expense'
                GROUP BY amount, category, description
                HAVING cnt >= 2
                ORDER BY cnt DESC, amount DESC
                LIMIT 10
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Analytics & Reporting Helpers ---
    async def get_category_totals(self, user_id: int, start_utc: datetime, end_utc: datetime) -> dict[str, int]:
        rows = await self.expenses_between(user_id, start_utc, end_utc)
        totals: dict[str, int] = {}
        for r in rows:
            if r.get("type", "expense") == "expense":
                cat = r["category"] or "Boshqa"
                totals[cat] = totals.get(cat, 0) + int(r["amount"])
        return totals

    async def get_top_spending_info(self, user_id: int, start_utc: datetime, end_utc: datetime) -> dict[str, Any]:
        """Find highest spending day and highest spending category for the given range."""
        return await asyncio.to_thread(self._get_top_spending_info_sync, user_id, start_utc, end_utc)

    def _get_top_spending_info_sync(self, user_id: int, start_utc: datetime, end_utc: datetime) -> dict[str, Any]:
        with self._connect() as conn:
            # Top category
            cat_row = conn.execute(
                """
                SELECT category, SUM(amount) as total
                FROM expenses
                WHERE user_id = ? AND type = 'expense'
                  AND datetime(created_at) >= datetime(?)
                  AND datetime(created_at) < datetime(?)
                GROUP BY category
                ORDER BY total DESC
                LIMIT 1
                """,
                (user_id, start_utc.strftime("%Y-%m-%d %H:%M:%S"), end_utc.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchone()

            # Top day
            day_row = conn.execute(
                """
                SELECT date(created_at) as day_str, SUM(amount) as total
                FROM expenses
                WHERE user_id = ? AND type = 'expense'
                  AND datetime(created_at) >= datetime(?)
                  AND datetime(created_at) < datetime(?)
                GROUP BY day_str
                ORDER BY total DESC
                LIMIT 1
                """,
                (user_id, start_utc.strftime("%Y-%m-%d %H:%M:%S"), end_utc.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchone()

            return {
                "top_category": cat_row["category"] if cat_row else None,
                "top_category_amount": int(cat_row["total"]) if cat_row else 0,
                "top_day": day_row["day_str"] if day_row else None,
                "top_day_amount": int(day_row["total"]) if day_row else 0,
            }

    async def get_month_comparison(self, user_id: int) -> dict[str, Any]:
        """Compare current month's expenses with previous month's expenses."""
        curr_start, curr_end = self.month_range()
        prev_start, prev_end = self.prev_month_range()

        curr_rows = await self.expenses_between(user_id, curr_start, curr_end)
        prev_rows = await self.expenses_between(user_id, prev_start, prev_end)

        curr_total = sum(int(r["amount"]) for r in curr_rows if r.get("type", "expense") == "expense")
        prev_total = sum(int(r["amount"]) for r in prev_rows if r.get("type", "expense") == "expense")

        diff_pct = 0.0
        if prev_total > 0:
            diff_pct = ((curr_total - prev_total) / prev_total) * 100.0

        # Category breakdowns
        curr_cats: dict[str, int] = {}
        for r in curr_rows:
            if r.get("type", "expense") == "expense":
                curr_cats[r["category"]] = curr_cats.get(r["category"], 0) + int(r["amount"])

        prev_cats: dict[str, int] = {}
        for r in prev_rows:
            if r.get("type", "expense") == "expense":
                prev_cats[r["category"]] = prev_cats.get(r["category"], 0) + int(r["amount"])

        cat_comparisons = []
        all_cats = set(curr_cats.keys()) | set(prev_cats.keys())
        for c in all_cats:
            c_amt = curr_cats.get(c, 0)
            p_amt = prev_cats.get(c, 0)
            c_pct = 0.0
            if p_amt > 0:
                c_pct = ((c_amt - p_amt) / p_amt) * 100.0
            cat_comparisons.append({
                "category": c,
                "current_amount": c_amt,
                "previous_amount": p_amt,
                "diff_percent": c_pct,
            })

        return {
            "current_total": curr_total,
            "previous_total": prev_total,
            "diff_percent": diff_pct,
            "categories": cat_comparisons,
        }

    async def get_all_transactions(self, user_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_all_transactions_sync, user_id)

    def _get_all_transactions_sync(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, amount, category, description, created_at, type
                FROM expenses
                WHERE user_id = ?
                ORDER BY datetime(created_at) DESC
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    async def get_active_user_ids(self) -> list[int]:
        return await asyncio.to_thread(self._get_active_user_ids_sync)

    def _get_active_user_ids_sync(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT user_id FROM expenses").fetchall()
            return [int(r["user_id"]) for r in rows]

    def day_range(self) -> tuple[datetime, datetime]:
        now = datetime.now(tz=self.tz)
        start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        return _to_utc(start_local), _to_utc(end_local)

    def week_range(self) -> tuple[datetime, datetime]:
        """Monday 00:00 through the end of today (exclusive tomorrow)."""
        now = datetime.now(tz=self.tz)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = today - timedelta(days=today.weekday())
        end_local = today + timedelta(days=1)
        return _to_utc(start_local), _to_utc(end_local)

    def month_range(self) -> tuple[datetime, datetime]:
        now = datetime.now(tz=self.tz)
        start_local = datetime(now.year, now.month, 1, tzinfo=self.tz)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = today + timedelta(days=1)
        return _to_utc(start_local), _to_utc(end_local)

    def prev_month_range(self) -> tuple[datetime, datetime]:
        now = datetime.now(tz=self.tz)
        first_of_this_month = datetime(now.year, now.month, 1, tzinfo=self.tz)
        last_day_prev_month = first_of_this_month - timedelta(days=1)
        first_of_prev_month = datetime(last_day_prev_month.year, last_day_prev_month.month, 1, tzinfo=self.tz)
        return _to_utc(first_of_prev_month), _to_utc(first_of_this_month)


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(ZoneInfo("UTC"))


