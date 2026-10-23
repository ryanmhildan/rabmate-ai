"""Unit normalization. Deliberately small: only spellings of the *same* unit are merged.

No conversions (m vs roll, sak vs kg): a price is only comparable when the unit is identical,
otherwise matching reports the difference and the price cannot be applied automatically.
"""

from __future__ import annotations

import re

_ALIASES: dict[str, str] = {
    "m³": "m3",
    "kubik": "m3",
    "meter kubik": "m3",
    "m²": "m2",
    "meter persegi": "m2",
    "meter": "m",
    "mtr": "m",
    "kilogram": "kg",
    "kgs": "kg",
    "lumpsum": "ls",
    "lump sum": "ls",
    "orang hari": "oh",
    "o-h": "oh",
    "zak": "sak",
    "buah": "bh",
    "pieces": "pcs",
    "piece": "pcs",
    "pc": "pcs",
    "liter": "l",
    "ltr": "l",
}


def normalize_unit(unit: str) -> str:
    text = re.sub(r"\s+", " ", unit.strip().lower()).rstrip(".")
    return _ALIASES.get(text, text)


def same_unit(a: str, b: str) -> bool:
    return normalize_unit(a) == normalize_unit(b)
