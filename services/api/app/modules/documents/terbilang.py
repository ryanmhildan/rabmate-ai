"""Amounts in Indonesian words ("terbilang"), as printed on Indonesian business documents."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_DIGITS = ("", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan")
# 10^3 groups: ribu, juta, miliar, triliun, kuadriliun (NUMERIC(20,2) stays below 10^18).
_SCALES = ("", "ribu", "juta", "miliar", "triliun", "kuadriliun")


def _below_thousand(n: int) -> list[str]:
    words: list[str] = []
    hundreds, rest = divmod(n, 100)
    if hundreds == 1:
        words.append("seratus")
    elif hundreds > 1:
        words += [_DIGITS[hundreds], "ratus"]
    if rest == 10:
        words.append("sepuluh")
    elif rest == 11:
        words.append("sebelas")
    elif 12 <= rest <= 19:
        words += [_DIGITS[rest - 10], "belas"]
    elif rest >= 20:
        tens, units = divmod(rest, 10)
        words += [_DIGITS[tens], "puluh"]
        if units:
            words.append(_DIGITS[units])
    elif rest > 0:
        words.append(_DIGITS[rest])
    return words


def terbilang(n: int) -> str:
    """Non-negative integer in words: 1000 → 'seribu', 1_000_000 → 'satu juta'."""
    if n < 0:
        raise ValueError("terbilang hanya untuk bilangan non-negatif")
    if n == 0:
        return "nol"
    groups: list[int] = []
    while n:
        n, group = divmod(n, 1000)
        groups.append(group)
    if len(groups) > len(_SCALES):
        raise ValueError("bilangan terlalu besar")
    words: list[str] = []
    for scale_index in range(len(groups) - 1, -1, -1):
        group = groups[scale_index]
        if group == 0:
            continue
        if scale_index == 1 and group == 1:
            words.append("seribu")
            continue
        words += _below_thousand(group)
        if _SCALES[scale_index]:
            words.append(_SCALES[scale_index])
    return " ".join(words)


def rupiah_in_words(amount: Decimal | str) -> str:
    """'Sepuluh juta dua ratus ribu rupiah lima puluh sen' (cents rounded half-up to 2 places)."""
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value < 0:
        raise ValueError("nilai negatif")
    whole = int(value)
    cents = int((value - whole) * 100)
    text = f"{terbilang(whole)} rupiah"
    if cents:
        text += f" {terbilang(cents)} sen"
    return text[0].upper() + text[1:]
