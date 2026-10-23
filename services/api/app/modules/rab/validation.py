"""RAB validation rules. Pure: works on plain facts so the API, imports and AI tools share it.

Errors block submission for review; warnings and info are shown but do not block.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.modules.rab.calculation import Adjustments, CalculationError, LineInput, calculate


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ItemFacts:
    id: uuid.UUID | None
    position: int
    code: str | None
    name: str
    quantity: Decimal
    unit_price: Decimal | None
    price_source: str | None
    # None = price not taken from the catalog; otherwise that catalog price's status.
    catalog_status: str | None = None


@dataclass(frozen=True)
class Issue:
    severity: Severity
    code: str
    message: str
    item_id: uuid.UUID | None = None


def validate(
    items: Sequence[ItemFacts], adjustments: Adjustments, tax_label: str | None
) -> list[Issue]:
    issues: list[Issue] = []
    if not items:
        issues.append(Issue(Severity.ERROR, "empty", "RAB belum memiliki item."))

    for item in items:
        label = f"Item {item.position} ({item.name})"
        if item.unit_price is None:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "missing_price",
                    f"{label} belum memiliki harga satuan.",
                    item.id,
                )
            )
            continue
        if item.unit_price == 0:
            issues.append(Issue(Severity.WARNING, "zero_price", f"{label} berharga nol.", item.id))
        if not (item.price_source or "").strip():
            issues.append(
                Issue(
                    Severity.WARNING,
                    "missing_price_source",
                    f"{label} tidak mencantumkan sumber harga.",
                    item.id,
                )
            )

    for item in items:
        if item.catalog_status is not None and item.catalog_status != "verified":
            issues.append(
                Issue(
                    Severity.WARNING,
                    "unverified_catalog_price",
                    f"Item {item.position} ({item.name}) memakai harga katalog yang belum "
                    "terverifikasi.",
                    item.id,
                )
            )

    codes = Counter(i.code.strip().lower() for i in items if i.code and i.code.strip())
    for code, count in sorted(codes.items()):
        if count > 1:
            issues.append(
                Issue(
                    Severity.WARNING, "duplicate_code", f"Kode item '{code}' dipakai {count} kali."
                )
            )

    try:
        calculate((LineInput(i.quantity, i.unit_price) for i in items), adjustments)
    except CalculationError as exc:
        issues.append(Issue(Severity.ERROR, exc.code, exc.message))

    if adjustments.tax_rate_percent is None or tax_label is None:
        issues.append(
            Issue(Severity.INFO, "no_tax", "Pajak belum dikonfigurasi; total tidak termasuk pajak.")
        )
    return issues


def has_errors(issues: Sequence[Issue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)
