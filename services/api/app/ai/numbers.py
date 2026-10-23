"""Deterministic reading of numbers the model copied from a source text.

The model never converts numbers: it copies the text as written ("1.250.000", "12,5"), and this
module parses it with the number format the user declared. Text that does not fit the format —
or that is not actually in the source — becomes "unknown" instead of a guessed value.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class NumberFormat(StrEnum):
    ID = "id"  # 1.234.567,89 — Indonesian: dot for thousands, comma for decimals
    EN = "en"  # 1,234,567.89


_PATTERNS = {
    NumberFormat.ID: (re.compile(r"^\d{1,3}(?:\.\d{3})+(?:,\d+)?$|^\d+(?:,\d+)?$"), ".", ","),
    NumberFormat.EN: (re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^\d+(?:\.\d+)?$"), ",", "."),
}
_NOISE = re.compile(r"(?i)^(?:rp\.?|idr)\s*|\s*(?:,-|\.-)$")
_SPACES = re.compile(r"\s+")
NBSP = chr(0xA0)


def parse_number(text: str | None, number_format: NumberFormat) -> Decimal | None:
    """The value of `text` in `number_format`; None when it is empty, negative or ambiguous."""
    if text is None:
        return None
    cleaned = _NOISE.sub("", text.strip()).replace(NBSP, "").replace(" ", "")
    if not cleaned:
        return None
    pattern, thousands, decimal = _PATTERNS[number_format]
    if not pattern.match(cleaned):
        return None
    try:
        return Decimal(cleaned.replace(thousands, "").replace(decimal, "."))
    except InvalidOperation:
        return None


def normalize_space(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def number_in(fragment: str, source: str) -> bool:
    """Whether the number text `fragment` occurs in `source` as a whole number.

    A substring test is not enough: "0" or "250.000" would be "found" inside "1.250.000".
    """
    needle = normalize_space(fragment)
    if not needle:
        return False
    pattern = rf"(?<![\d.,]){re.escape(needle)}(?![\d]|[.,]\d)"
    return re.search(pattern, normalize_space(source), flags=re.IGNORECASE) is not None


_NUMBER_TOKEN = re.compile(r"\d[\d.,]*\d|\d")


def document_number(copied: str, line: str) -> str | None:
    """The number as the document writes it, when the model re-formatted it on the way.

    Small models sometimes copy "3.850.000" as "3,850,000". Only when exactly one number on the
    item's own line has the same digits is that document text returned; the model's text itself
    is never parsed.
    """
    digits = re.sub(r"\D", "", copied)
    if not digits:
        return None
    matches = {t for t in _NUMBER_TOKEN.findall(line) if re.sub(r"\D", "", t) == digits}
    return matches.pop() if len(matches) == 1 else None


def appears_in(fragment: str, source: str) -> bool:
    """Whether `fragment` occurs in `source` (whitespace-insensitive, case-insensitive)."""
    needle = normalize_space(fragment).lower()
    return bool(needle) and needle in normalize_space(source).lower()
