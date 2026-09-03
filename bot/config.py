"""Load settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root: money/
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_id: int | None
    database_path: Path
    timezone: str
    gemini_api_key: str


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    user_id_raw = os.getenv("ALLOWED_USER_ID", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and fill it in.")

    allowed_user_id = int(user_id_raw) if user_id_raw.isdigit() else None

    db_path = Path(os.getenv("DATABASE_PATH", str(ROOT_DIR / "data" / "expenses.db")))
    if not db_path.is_absolute():
        db_path = ROOT_DIR / db_path

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    return Settings(
        bot_token=token,
        allowed_user_id=allowed_user_id,
        database_path=db_path,
        timezone=os.getenv("TIMEZONE", "Asia/Tashkent").strip() or "Asia/Tashkent",
        gemini_api_key=gemini_key,
    )

