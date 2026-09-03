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


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(ZoneInfo("UTC"))

