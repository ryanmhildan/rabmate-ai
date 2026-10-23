"""Indonesian display formatting for generated documents. Pure functions on Decimal / ISO strings.

Values arrive from the snapshot as decimal strings and are formatted digit by digit — never via
float — so a document shows exactly what the database stored.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

JAKARTA = ZoneInfo("Asia/Jakarta")

MONTHS = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)


def _group(digits: str) -> str:
    """'1234567' → '1.234.567'."""
    head = len(digits) % 3 or 3
    parts = [digits[:head]] + [digits[i : i + 3] for i in range(head, len(digits), 3)]
    return ".".join(parts)


def number(value: str | Decimal, *, min_places: int = 0, max_places: int = 2) -> str:
    """Indonesian number: '.' thousands, ',' decimals; trailing zeros trimmed to `min_places`."""
    amount = Decimal(value)
    negative = amount < 0
    text = format(abs(amount), "f")
    whole, _, fraction = text.partition(".")
    fraction = fraction[:max_places].rstrip("0") if max_places else ""
    if len(fraction) < min_places:
        fraction = fraction.ljust(min_places, "0")
    result = _group(whole) + ("," + fraction if fraction else "")
    return ("-" if negative and result.strip("0.,") else "") + result


def money(value: str | Decimal | None, currency: str = "IDR") -> str:
    """'Rp 1.250.000' for whole amounts, 'Rp 1.250.000,50' when there are cents."""
    if value is None:
        return "—"
    amount = Decimal(value)
    places = 2 if amount != amount.to_integral_value() else 0
    formatted = number(amount, min_places=places, max_places=2)
    prefix = "Rp" if currency == "IDR" else currency
    return f"{prefix} {formatted}"


def unit_price(value: str | Decimal | None, currency: str = "IDR") -> str:
    """Unit prices keep up to 4 decimals (NUMERIC(20,4)); a fraction shows at least 2 (cents)."""
    if value is None:
        return "—"
    amount = Decimal(value)
    places = 0 if amount == amount.to_integral_value() else 2
    prefix = "Rp" if currency == "IDR" else currency
    return f"{prefix} {number(amount, min_places=places, max_places=4)}"


def quantity(value: str | Decimal) -> str:
    return number(value, max_places=4)


def percent(value: str | Decimal) -> str:
    return number(value, max_places=2)


def tanggal(value: str | date | datetime | None) -> str:
    """'19 Oktober 2026'. Datetimes are shown in Asia/Jakarta."""
    if value is None:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
    if isinstance(value, datetime):
        value = value.astimezone(JAKARTA).date()
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def tanggal_waktu(value: str | datetime | None) -> str:
    """'19 Oktober 2026 pukul 03.14 WIB'."""
    if value is None:
        return "—"
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    local = moment.astimezone(JAKARTA)
    return f"{tanggal(local.date())} pukul {local:%H.%M} WIB"
