"""Gemini AI Service for FinMate Bot.

Handles NLP expense extraction, audio speech-to-text parsing, receipt image OCR,
and personalized financial advice using Google Gemini API.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import google.generativeai as genai

log = logging.getLogger(__name__)


def _init_gemini(api_key: str) -> bool:
    if not api_key:
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        log.error("Failed to configure Gemini API: %s", e)
        return False


def parse_text_with_gemini(
    api_key: str,
    text: str,
    categories: list[str] | None = None,
) -> dict[str, Any] | None:
    """Use Gemini API to extract {amount, category, description, type} from text."""
    if not _init_gemini(api_key):
        return None

    cat_list = ", ".join(categories) if categories else "Oziq-ovqat, Transport, Kofe/Kafe, Xarid, Kommunal, Ko'ngilochar, Maosh, Boshqa"

    prompt = f"""You are a smart financial transaction parser for Uzbek language Telegram bot.
Extract the transaction details from this text: "{text}"

Allowed categories: [{cat_list}]

Respond STRICTLY with JSON without markdown wrappers or code blocks:
{{
  "amount": integer (in UZS, e.g. 25000 for '25 ming' or '25k', 1500000 for '1.5 mln'),
  "category": "matching category from allowed list",
  "description": "short description of item or activity",
  "type": "expense" or "income"
}}

If no transaction amount can be determined, output null.
"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        resp_text = (response.text or "").strip()
        
        # Clean json formatting markdown
        resp_text = re.sub(r"^```json\s*", "", resp_text, flags=re.IGNORECASE)
        resp_text = re.sub(r"^```\s*", "", resp_text)
        resp_text = re.sub(r"\s*```$", "", resp_text)
        resp_text = resp_text.strip()

        if not resp_text or resp_text == "null":
            return None

        data = json.loads(resp_text)
        if isinstance(data, dict) and "amount" in data and data["amount"]:
            amount = int(data["amount"])
            if amount > 0:
                return {
                    "amount": amount,
                    "category": str(data.get("category") or "Boshqa"),
                    "description": str(data.get("description") or ""),
                    "type": str(data.get("type") or "expense").lower(),
                }
    except Exception as e:
        log.warning("Gemini NLP parsing failed: %s", e)

    return None


def transcribe_and_parse_audio(
    api_key: str,
    audio_bytes: bytes,
    mime_type: str,
    categories: list[str] | None = None,
) -> dict[str, Any] | None:
    """Transcribe voice message and parse transaction info with Gemini."""
    if not _init_gemini(api_key):
        return None

    cat_list = ", ".join(categories) if categories else "Oziq-ovqat, Transport, Kofe/Kafe, Xarid, Kommunal, Ko'ngilochar, Maosh, Boshqa"

    prompt = f"""Listen carefully to this Uzbek voice audio message.
Extract transaction details in JSON format:
{{
  "amount": integer (amount in UZS),
  "category": "matching category from [{cat_list}]",
  "description": "short summary",
  "type": "expense" or "income",
  "transcript": "transcribed speech in Uzbek"
}}

If no financial transaction is mentioned, output null.
Respond STRICTLY with valid JSON.
"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        contents = [
            {"mime_type": mime_type, "data": audio_bytes},
            prompt,
        ]
        response = model.generate_content(contents)
        resp_text = (response.text or "").strip()
        resp_text = re.sub(r"^```json\s*", "", resp_text, flags=re.IGNORECASE)
        resp_text = re.sub(r"^```\s*", "", resp_text)
        resp_text = re.sub(r"\s*```$", "", resp_text).strip()

        if not resp_text or resp_text == "null":
            return None

        data = json.loads(resp_text)
        if isinstance(data, dict) and "amount" in data and data["amount"]:
            amount = int(data["amount"])
            if amount > 0:
                return {
                    "amount": amount,
                    "category": str(data.get("category") or "Boshqa"),
                    "description": str(data.get("description") or ""),
                    "type": str(data.get("type") or "expense").lower(),
                    "transcript": str(data.get("transcript") or ""),
                }
    except Exception as e:
        log.warning("Gemini Audio parsing failed: %s", e)

    return None


def ocr_receipt_image(
    api_key: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    categories: list[str] | None = None,
) -> dict[str, Any] | None:
    """OCR payment receipt photo and extract shop name, amount, category using Gemini Vision."""
    if not _init_gemini(api_key):
        return None

    cat_list = ", ".join(categories) if categories else "Oziq-ovqat, Transport, Kofe/Kafe, Xarid, Kommunal, Ko'ngilochar, Boshqa"

    prompt = f"""Read this payment receipt / check image.
Extract total transaction amount in UZS, store name, and guess category from [{cat_list}].

Respond STRICTLY in JSON format:
{{
  "amount": integer (total sum paid in UZS),
  "store": "store or organization name",
  "category": "guessed category",
  "description": "brief item breakdown or store name"
}}

If it is not a payment receipt or amount is unreadable, output null.
"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        contents = [
            {"mime_type": mime_type, "data": image_bytes},
            prompt,
        ]
        response = model.generate_content(contents)
        resp_text = (response.text or "").strip()
        resp_text = re.sub(r"^```json\s*", "", resp_text, flags=re.IGNORECASE)
        resp_text = re.sub(r"^```\s*", "", resp_text)
        resp_text = re.sub(r"\s*```$", "", resp_text).strip()

        if not resp_text or resp_text == "null":
            return None

        data = json.loads(resp_text)
        if isinstance(data, dict) and "amount" in data and data["amount"]:
            amount = int(data["amount"])
            if amount > 0:
                return {
                    "amount": amount,
                    "store": str(data.get("store") or "Do'kon"),
                    "category": str(data.get("category") or "Xarid"),
                    "description": str(data.get("description") or data.get("store") or "Chek xarajati"),
                }
    except Exception as e:
        log.warning("Gemini Receipt OCR failed: %s", e)

    return None


def get_financial_advice(
    api_key: str,
    user_context: str,
    user_question: str,
) -> str:
    """Generate financial advice based on actual user expense/income history context."""
    if not _init_gemini(api_key):
        return "⚠️ Gemini API kaliti kiritilmagan. Maslahatchi rejimidan foydalanish uchun `.env` faylda `GEMINI_API_KEY`ni sozlang."

    prompt = f"""Siz FinMate botining shaxsiy moliya bo'yicha sun'iy intellekt maslahatchisisiz.
Foydalanuvchining real moliyaviy ma'lumotlari:
---
{user_context}
---

Foydalanuvchi savoli: "{user_question}"

Foydalanuvchiga uning real xarajat va daromadlariga asoslangan, amaliy, do'stona va foydali maslahatlar bering (o'zbek tilida). Javobingiz aniq va tushunarli bo'lsin.
"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return (response.text or "").strip()
    except Exception as e:
        log.warning("Gemini advice request failed: %s", e)
        return f"⚠️ Maslahat olishda xatolik yuz berdi: {e}"
