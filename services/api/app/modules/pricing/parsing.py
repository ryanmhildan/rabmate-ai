"""Strict parsing of spreadsheet cell values. Pure.

Ambiguity is rejected rather than guessed: "4.500" could be 4.5 or 4500, so it is an error;
"4500", "4500.75", "4.500,75" and "4500,75" are accepted. Formulas are never evaluated.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class CellError(ValueError):
    pass


_PLAIN = re.compile(r"^-?\d+(\.\d+)?$")
_ID_FULL = re.compile(r"^-?\d{1,3}(\.\d{3})+,\d+$")  # 4.500,75 / 1.250.000,5
_ID_THOUSANDS = re.compile(r"^-?[1-9]\d{0,2}(\.\d{3})+$")  # 4.500 (ambiguous; 0.125 is not)
_COMMA_DECIMAL = re.compile(r"^-?\d+,\d+$")  # 4500,75
_EN_FULL = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")  # 1,250,000.50


def parse_decimal(value: object, *, max_places: int, label: str) -> Decimal | None:
    """Parses a number cell; returns None for empty cells."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise CellError(f"{label}: nilai tidak valid.")
    if isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        # Spreadsheet numbers arrive as binary floats; repr() is the shortest exact round-trip,
        # so 4500.75 stays 4500.75 instead of 4500.75000000000045474735...
        result = Decimal(repr(value))
    elif isinstance(value, Decimal):
        result = value
    else:
        text = str(value).strip()
        if not text:
            return None
        text = re.sub(r"(?i)^(rp\.?|idr)\s*", "", text).replace(" ", "")
        # Checked first: "4.500" also looks like a plain decimal (4.5) but usually means 4500.
        if _ID_THOUSANDS.match(text) or _EN_FULL.match(text):
            raise CellError(
                f"{label}: format angka '{value}' ambigu. Tulis tanpa pemisah ribuan, "
                "mis. 4500 atau 4500,75."
            )
        if _PLAIN.match(text):
            normalized = text
        elif _ID_FULL.match(text):
            normalized = text.replace(".", "").replace(",", ".")
        elif _COMMA_DECIMAL.match(text):
            normalized = text.replace(",", ".")
        else:
            raise CellError(f"{label}: '{value}' bukan angka.")
        try:
            result = Decimal(normalized)
        except InvalidOperation:
            raise CellError(f"{label}: '{value}' bukan angka.") from None

    if not result.is_finite():
        raise CellError(f"{label}: nilai tidak valid.")
    exponent = result.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > max_places:
        raise CellError(f"{label}: maksimal {max_places} angka desimal.")
    return result


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_DATE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")


def parse_date(value: object, *, label: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if _ISO_DATE.match(text):
            return date.fromisoformat(text)
        match = _ID_DATE.match(text)
        if match:  # Indonesian order: day/month/year
            day, month, year = (int(g) for g in match.groups())
            return date(year, month, day)
    except ValueError:
        pass
    raise CellError(
        f"{label}: tanggal '{value}' tidak dikenali (gunakan YYYY-MM-DD atau DD/MM/YYYY)."
    )


def parse_text(value: object, *, max_length: int, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        text = repr(value)[:-2] if value.is_integer() else repr(value)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise CellError(f"{label}: maksimal {max_length} karakter.")
    return text


_URL = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)


def parse_url(value: object, *, label: str) -> str | None:
    text = parse_text(value, max_length=1000, label=label)
    if text is None:
        return None
    if not _URL.match(text):
        raise CellError(f"{label}: hanya URL http/https yang diterima.")
    return text
