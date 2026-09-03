"""Gemini AI Service for FinMate Bot.

Handles NLP expense extraction, audio speech-to-text parsing, receipt image OCR,
and personalized financial advice using official new google-genai SDK.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

MODEL_CANDIDATES = [
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def _get_client(api_key: str) -> tuple[genai.Client | None, str | None]:
    """Create official genai.Client or return error code."""
    if not api_key or api_key.strip() == "" or "your_gemini_api_key" in api_key:
        return None, "api_key_missing"
    try:
        client = genai.Client(api_key=api_key)
        return client, None
    except Exception as e:
        log.error("Failed to create genai.Client: %s", e)
        return None, str(e)


def _generate_with_fallback(client: genai.Client, contents: Any) -> Any:
    """Execute generate_content with model fallback for maximum resilience."""
    last_error = None
    for model_name in MODEL_CANDIDATES:
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents,
            )
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str:
                last_error = e
                continue
            else:
                raise e

    if last_error:
        raise last_error
    raise RuntimeError("No available Gemini model succeeded.")


def parse_text_with_gemini(
    api_key: str,
    text: str,
    categories: list[str] | None = None,
) -> dict[str, Any] | None:
    """Use Gemini API to extract {amount, category, description, type} from text."""
    client, err = _get_client(api_key)
    if err:
        return {"error": err}

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
        response = _generate_with_fallback(client, prompt)
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
                }
    except Exception as e:
        log.warning("Gemini NLP parsing failed: %s", e)
        return {"error": str(e)}

    return None


def transcribe_and_parse_audio(
    api_key: str,
    audio_bytes: bytes,
    mime_type: str,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """Transcribe voice message and parse transaction info with google-genai SDK."""
    client, err = _get_client(api_key)
    if err:
        return {"error": err}

    cat_list = ", ".join(categories) if categories else "Oziq-ovqat, Transport, Kofe/Kafe, Xarid, Kommunal, Ko'ngilochar, Maosh, Boshqa"

    prompt = f"""Listen carefully to this voice audio message in Uzbek / Russian / English.
First transcribe the exact spoken words into 'transcript' field.
Then extract the transaction sum (in UZS currency integer) and category.

Uzbek numbers might be spoken in words (e.g. 'on besh ming' = 15000, 'yigirma ming' = 20000, 'o\'n ikki ming' = 12000, 'yuz ming' = 100000, 'bir million' = 1000000).

Allowed categories: [{cat_list}]

Respond STRICTLY in JSON format:
{{
  "transcript": "transcribed spoken words",
  "amount": integer or null (e.g. 15000),
  "category": "matching category",
  "description": "short summary of item",
  "type": "expense" or "income"
}}
"""

    try:
        contents = [
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            prompt,
        ]
        response = _generate_with_fallback(client, contents)
        resp_text = (response.text or "").strip()
        resp_text = re.sub(r"^```json\s*", "", resp_text, flags=re.IGNORECASE)
        resp_text = re.sub(r"^```\s*", "", resp_text)
        resp_text = re.sub(r"\s*```$", "", resp_text).strip()

        if not resp_text or resp_text == "null":
            return {}

        data = json.loads(resp_text)
        if isinstance(data, dict):
            transcript = str(data.get("transcript") or "").strip()
            raw_amount = data.get("amount")
            amount = None
            if raw_amount:
                try:
                    cleaned_amt = re.sub(r"[^\d]", "", str(raw_amount))
                    if cleaned_amt:
                        amount = int(cleaned_amt)
                except Exception:
                    pass

            return {
                "transcript": transcript,
                "amount": amount if (amount and amount > 0) else None,
                "category": str(data.get("category") or "Boshqa"),
                "description": str(data.get("description") or transcript),
                "type": str(data.get("type") or "expense").lower(),
            }
    except Exception as e:
        log.warning("Gemini Audio parsing failed: %s", e)
        return {"error": str(e)}

    return {}


def ocr_receipt_image(
    api_key: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """OCR payment receipt photo and extract shop name, amount, category using google-genai SDK."""
    client, err = _get_client(api_key)
    if err:
        return {"error": err}

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
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt,
        ]
        response = _generate_with_fallback(client, contents)
        resp_text = (response.text or "").strip()
        resp_text = re.sub(r"^```json\s*", "", resp_text, flags=re.IGNORECASE)
        resp_text = re.sub(r"^```\s*", "", resp_text)
        resp_text = re.sub(r"\s*```$", "", resp_text).strip()

        if not resp_text or resp_text == "null":
            return {}

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
        return {"error": str(e)}

    return {}


def get_financial_advice(
    api_key: str,
    user_context: str,
    user_question: str,
) -> str:
    """Generate financial advice based on actual user expense/income history context."""
    client, err = _get_client(api_key)
    if err == "api_key_missing":
        return "⚠️ Gemini API kaliti sozlanmagan. Serverdagi `.env` faylida `GEMINI_API_KEY`ni to'ldiring."
    elif err:
        return f"⚠️ Gemini API sozlashda xatolik: {err}"

    prompt = f"""Siz FinMate botining shaxsiy moliya bo'yicha sun'iy intellekt maslahatchisisiz.
Foydalanuvchining real moliyaviy ma'lumotlari:
---
{user_context}
---

Foydalanuvchi savoli: "{user_question}"

Foydalanuvchiga uning real xarajat va daromadlariga asoslangan, amaliy, do'stona va foydali maslahatlar bering (o'zbek tilida). Javobingiz aniq va tushunarli bo'lsin.
"""

    try:
        response = _generate_with_fallback(client, prompt)
        return (response.text or "").strip()
    except Exception as e:
        log.warning("Gemini advice request failed: %s", e)
        return f"⚠️ Maslahat olishda xatolik yuz berdi: {e}"
