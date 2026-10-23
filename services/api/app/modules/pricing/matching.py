"""Explainable scoring of price candidates against a requested item. Pure.

Similar names are never enough on their own: unit, size/number tokens (e.g. "cat6", "10mm",
"2.5"), brand and freshness are checked explicitly and every deviation is reported. A candidate
with a different unit is never ranked above "low" and cannot be applied automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from enum import StrEnum

from app.modules.pricing.units import same_unit

STALE_AFTER_DAYS = 180

_STOPWORDS = frozenset(
    {"dan", "atau", "untuk", "dengan", "yang", "di", "ke", "dari", "per", "the", "and", "of", "for"}
)
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class MatchLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_LEVEL_ORDER = {MatchLevel.LOW: 0, MatchLevel.MEDIUM: 1, MatchLevel.HIGH: 2}


@dataclass(frozen=True)
class Query:
    name: str
    unit: str | None = None
    specification: str | None = None
    brand: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class Candidate:
    name: str
    unit: str
    specification: str | None = None
    brand: str | None = None
    location: str | None = None
    observed_at: date | None = None
    verified: bool = False


@dataclass(frozen=True)
class MatchResult:
    score: int
    level: MatchLevel
    unit_compatible: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    found = _TOKEN.findall(text.lower().replace(",", "."))
    return {t for t in found if t not in _STOPWORDS}


def numbers(*texts: str | None) -> set[str]:
    """Numeric values in the text, so "Cat6", "Cat 6" and "cat-6" all yield {"6"}."""
    found: set[str] = set()
    for text in texts:
        for raw in _NUMBER.findall((text or "").replace(",", ".")):
            value = raw.rstrip("0").rstrip(".") if "." in raw else raw.lstrip("0") or "0"
            found.add(value)
    return found


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cap(level: MatchLevel, ceiling: MatchLevel) -> MatchLevel:
    return level if _LEVEL_ORDER[level] <= _LEVEL_ORDER[ceiling] else ceiling


def score(query: Query, candidate: Candidate, *, today: date) -> MatchResult:
    q_name, c_name = tokens(query.name), tokens(candidate.name)
    name_overlap = _jaccard(q_name, c_name)
    name_ratio = SequenceMatcher(
        None, query.name.lower().strip(), candidate.name.lower().strip()
    ).ratio()
    points = 60 * name_overlap + 20 * name_ratio
    reasons: list[str] = []
    warnings: list[str] = []
    ceiling = MatchLevel.HIGH

    if name_overlap >= 0.6:
        reasons.append("Nama sangat mirip.")
    elif name_overlap > 0:
        reasons.append(f"Kata yang sama: {', '.join(sorted(q_name & c_name))}.")

    # Sizes, types and grades carry meaning ("cat6" vs "cat5e", "10mm" vs "12mm").
    q_num = numbers(query.name, query.specification)
    c_num = numbers(candidate.name, candidate.specification)
    if q_num:
        missing = q_num - c_num
        if missing:
            warnings.append(
                f"Ukuran/tipe tidak cocok atau tidak tercantum: {', '.join(sorted(missing))}."
            )
            ceiling = _cap(ceiling, MatchLevel.MEDIUM)
        else:
            points += 10
            reasons.append("Ukuran/tipe cocok.")

    spec_overlap = _jaccard(tokens(query.specification), tokens(candidate.specification))
    points += 10 * spec_overlap

    unit_ok = True
    if query.unit:
        unit_ok = same_unit(query.unit, candidate.unit)
        if unit_ok:
            reasons.append("Satuan sama.")
        else:
            warnings.append(
                f"Satuan berbeda ({candidate.unit} vs {query.unit}); "
                "harga tidak dapat dipakai langsung."
            )
            ceiling = MatchLevel.LOW

    if query.brand:
        if candidate.brand and candidate.brand.strip().lower() == query.brand.strip().lower():
            reasons.append("Merek sama.")
        else:
            warnings.append(f"Merek berbeda atau tidak tercantum (diminta: {query.brand}).")
            ceiling = _cap(ceiling, MatchLevel.MEDIUM)

    if (
        query.location
        and candidate.location
        and candidate.location.strip().lower() != query.location.strip().lower()
    ):
        warnings.append(f"Lokasi pasar berbeda ({candidate.location}).")

    if not candidate.verified:
        warnings.append("Harga belum terverifikasi.")
    if (
        candidate.observed_at is not None
        and (today - candidate.observed_at).days > STALE_AFTER_DAYS
    ):
        warnings.append(
            f"Harga diperoleh {candidate.observed_at.isoformat()} (lebih dari 6 bulan lalu)."
        )

    total = round(min(points, 100))
    level = MatchLevel.HIGH if total >= 75 else MatchLevel.MEDIUM if total >= 45 else MatchLevel.LOW
    return MatchResult(
        score=total,
        level=_cap(level, ceiling),
        unit_compatible=unit_ok,
        reasons=reasons,
        warnings=warnings,
    )
