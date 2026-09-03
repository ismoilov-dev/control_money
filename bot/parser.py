"""Parse amounts and guess expense categories from casual Uzbek/Russian/English text."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Built-in categories. Keywords are matched against lowercase tokens
# (including agglutinated forms like "ovqatga" / "taksida").
DEFAULT_CATEGORIES: dict[str, dict[str, object]] = {
    "Transport": {
        "emoji": "🚕",
        "keywords": (
            "taksi",
            "taxi",
            "такси",
            "avtobus",
            "автобус",
            "marshrut",
            "метро",
            "metro",
            "benzin",
            "бензин",
            "yoqilg",
            "yandex",
            "uber",
            "bolt",
            "parking",
            "parkovka",
        ),
    },
    "Food": {
        "emoji": "🍽",
        "keywords": (
            "ovqat",
            "oziq",
            "oziq-ovqat",
            "еда",
            "food",
            "non",
            "restoran",
            "ресторан",
            "kafe",
            "кафе",
            "kofe",
            "кофе",
            "coffee",
            "choy",
            "чай",
            "lunch",
            "dinner",
            "mahsulot",
            "market",
            "supermarket",
            "magazin",
            "продукт",
        ),
    },
    "Clothing": {
        "emoji": "👕",
        "keywords": (
            "kiyim",
            "одежд",
            "poyabzal",
            "обув",
            "shirt",
            "ko'ylak",
            "koylak",
            "shim",
            "jeans",
        ),
    },
    "Utilities": {
        "emoji": "💡",
        "keywords": (
            "kommunal",
            "коммунал",
            "svet",
            "свет",
            "gaz",
            "газ",
            "suv",
            "вода",
            "internet",
            "интернет",
            "wifi",
            "wi-fi",
            "elektr",
            "ток",
        ),
    },
    "Rent": {
        "emoji": "🏠",
        "keywords": (
            "uy",
            "ijara",
            "аренда",
            "rent",
            "kvartira",
            "квартира",
            "uy-joy",
        ),
    },
    "Salary": {
        "emoji": "💰",
        "keywords": (
            "maosh",
            "oylik",
            "зарплата",
            "zarplata",
            "salary",
            "ish haq",
        ),
    },
    "Freelance": {
        "emoji": "💻",
        "keywords": (
            "frilans",
            "freelance",
            "фриланс",
            "proekt",
            "projekt",
        ),
    },
    "Gift": {
        "emoji": "🎁",
        "keywords": (
            "sovg'a",
            "sovga",
            "podarok",
            "подарок",
            "gift",
            "hadya",
            "xadya",
        ),
    },
    "Other": {
        "emoji": "📦",
        "keywords": ("boshqa", "другое", "other", "har xil"),
    },
}

# Short keywords that would false-positive inside longer words (e.g. "uy" in "buyurtma").
# These only match a token that equals the keyword or starts with it.
SHORT_KEYWORDS = {"uy", "gaz", "suv", "non", "choy"}

INCOME_KEYWORDS = {
    "maosh",
    "kirim",
    "daromad",
    "oldim",
    "oylik",
    "zarplata",
    "frilans",
    "freelance",
    "sovg'a",
    "sovga",
    "podarok",
    "hadya",
    "xadya",
    "доход",
    "зарплата",
    "фриланс",
    "подарок",
}

# 150k / 150 к / 2.5ming / 30 000 / 200000
_AMOUNT_RE = re.compile(
    r"""
    (?P<num>
        \d{1,3}(?:[ \u00a0_]\d{3})+   # 30 000 or 1_500_000
        |\d+(?:[.,]\d+)?              # 30000 or 150.5
    )
    \s*(?P<suffix>k|к|ming|минг)?
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedExpense:
    amount: int
    category: str | None
    description: str
    type: str = "expense"


def format_money(amount: int) -> str:
    """Format UZS with thin spaces: 150000 -> '150 000'."""
    return f"{amount:,}".replace(",", " ")


def category_emoji(name: str, extra: dict[str, str] | None = None) -> str:
    if extra and name in extra:
        return extra[name]
    data = DEFAULT_CATEGORIES.get(name)
    if data:
        return str(data["emoji"])
    return "📌"


def _is_income_text(text: str) -> bool:
    clean = text.lstrip()
    if clean.startswith("-"):
        return False
    if clean.startswith("+"):
        return True
    tokens = _tokenize(text)
    for token in tokens:
        for kw in INCOME_KEYWORDS:
            if _token_matches(token, kw.lower()):
                return True
    return False


def parse_expense(
    text: str,
    extra_keywords: dict[str, list[str]] | None = None,
) -> ParsedExpense | None:
    """Extract amount + optional category from a free-form message.

    Returns None when no plausible money amount is found.
    """
    amount, span = _extract_amount(text)
    if amount is None or span is None:
        return None

    is_income = _is_income_text(text)
    tx_type = "income" if is_income else "expense"

    leftover = (text[: span[0]] + " " + text[span[1] :]).strip()
    leftover = re.sub(r"^[\+\-]\s*", "", leftover)
    leftover = re.sub(r"\s+", " ", leftover).strip()

    category = guess_category(leftover or text, extra_keywords)
    return ParsedExpense(
        amount=amount,
        category=category,
        description=leftover,
        type=tx_type,
    )


def guess_category(
    text: str,
    extra_keywords: dict[str, list[str]] | None = None,
) -> str | None:
    """Return a category name if keywords match confidently, else None."""
    tokens = _tokenize(text)
    if not tokens:
        return None

    scores: dict[str, int] = {}
    catalog = _keyword_catalog(extra_keywords)

    for category, keywords in catalog.items():
        best = 0
        for kw in keywords:
            kw = kw.lower().strip()
            if not kw:
                continue
            if any(_token_matches(token, kw) for token in tokens):
                best = max(best, len(kw))
        if best:
            scores[category] = best

    if not scores:
        return None

    # Longest matching keyword wins (e.g. "oziq-ovqat" over a short clash).
    winner = max(scores.items(), key=lambda item: item[1])
    tied = [name for name, score in scores.items() if score == winner[1]]
    if len(tied) > 1:
        return None
    return winner[0]


def _keyword_catalog(
    extra_keywords: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    catalog: dict[str, list[str]] = {}
    for name, data in DEFAULT_CATEGORIES.items():
        catalog[name] = list(data["keywords"])  # type: ignore[arg-type]
        catalog[name].append(name.lower())
    if extra_keywords:
        for name, words in extra_keywords.items():
            catalog.setdefault(name, [])
            catalog[name].extend(words)
            catalog[name].append(name.lower())
    return catalog


def _extract_amount(text: str) -> tuple[int | None, tuple[int, int] | None]:
    candidates: list[tuple[int, tuple[int, int]]] = []
    for match in _AMOUNT_RE.finditer(text):
        raw_num = match.group("num").replace(" ", "").replace("\u00a0", "").replace("_", "")
        raw_num = raw_num.replace(",", ".")
        try:
            value = float(raw_num)
        except ValueError:
            continue
        suffix = (match.group("suffix") or "").lower()
        if suffix in {"k", "к", "ming", "минг"}:
            value *= 1000
        elif value < 1000:
            value *= 1000
        amount = int(round(value))
        if amount <= 0:
            continue
        candidates.append((amount, (match.start(), match.end())))

    if not candidates:
        return None, None

    # Prefer the largest number — usually the actual price, not a stray digit.
    amount, span = max(candidates, key=lambda item: item[0])
    return amount, span


def _tokenize(text: str) -> list[str]:
    normalized = text.lower().replace("'", "'").replace("`", "'")
    return [tok for tok in re.split(r"[^a-zA-Zа-яА-ЯёЁўқғҳʼ']+", normalized) if tok]


def _token_matches(token: str, keyword: str) -> bool:
    keyword = keyword.replace("'", "'")
    if keyword in SHORT_KEYWORDS or len(keyword) <= 2:
        return token == keyword or token.startswith(keyword)
    if token == keyword or token.startswith(keyword):
        return True
    # Allow "ovqat" inside "ovqatga" / "oziqovqat" for longer stems.
    return len(keyword) >= 4 and keyword in token



