"""Deterministic RAB arithmetic. Pure functions: no I/O, no ORM, no floats.

Order of computation (also documented in docs/DECISIONS.md ADR-022):

    line_subtotal   = round2(quantity * unit_price)            per item with a price
    subtotal        = Σ line_subtotal
    discount_amount = 0 | round2(subtotal * pct / 100) | fixed amount (≤ subtotal)
    taxable_base    = subtotal - discount_amount               (DPP)
    tax_amount      = round2(taxable_base * rate / 100)        only if a tax is configured
    grand_total     = taxable_base + tax_amount

round2 = ROUND_HALF_UP to 2 decimals. Items without a unit price contribute nothing and are
reported, so a draft can be saved incomplete but cannot be submitted (see validation.py).
This module is the single source of truth: the API, exports and AI tools all call it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal(100)

# NUMERIC(20, 2) holds at most 18 integer digits.
MAX_AMOUNT = Decimal("999999999999999999.99")

# Wide enough that any product of the stored column sizes (quantity 18,4 * unit price 20,4: up to
# 38 significant digits) is exact before rounding, so even out-of-range results are measured
# precisely by the overflow check instead of being silently rounded by the default 28 digits.
_PRECISION = 60


class DiscountType(StrEnum):
    NONE = "none"
    PERCENT = "percent"
    AMOUNT = "amount"


class CalculationError(ValueError):
    """Inputs that cannot produce a valid total (overflow, discount larger than subtotal)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LineInput:
    quantity: Decimal
    unit_price: Decimal | None


@dataclass(frozen=True)
class Adjustments:
    discount_type: DiscountType = DiscountType.NONE
    discount_value: Decimal = ZERO
    tax_rate_percent: Decimal | None = None


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    discount_amount: Decimal
    taxable_base: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    priced_items: int
    unpriced_items: int


def round2(value: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _check_amount(value: Decimal, what: str) -> Decimal:
    if abs(value) > MAX_AMOUNT:
        raise CalculationError("amount_overflow", f"{what} melebihi batas nilai yang didukung.")
    return value


def line_subtotal(quantity: Decimal, unit_price: Decimal | None) -> Decimal | None:
    if unit_price is None:
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return _check_amount(round2(quantity * unit_price), "Subtotal item")


def discount_amount(subtotal: Decimal, adjustments: Adjustments) -> Decimal:
    match adjustments.discount_type:
        case DiscountType.NONE:
            return ZERO
        case DiscountType.PERCENT:
            if not ZERO <= adjustments.discount_value <= HUNDRED:
                raise CalculationError("discount_invalid", "Diskon persen harus 0-100.")
            with localcontext() as ctx:
                ctx.prec = _PRECISION
                return round2(subtotal * adjustments.discount_value / HUNDRED)
        case DiscountType.AMOUNT:
            amount = round2(adjustments.discount_value)
            if amount < ZERO:
                raise CalculationError("discount_invalid", "Diskon tidak boleh negatif.")
            if amount > subtotal:
                raise CalculationError(
                    "discount_exceeds_subtotal", "Diskon tidak boleh melebihi subtotal."
                )
            return amount


def calculate(lines: Iterable[LineInput], adjustments: Adjustments) -> Totals:
    subtotal = ZERO
    priced = unpriced = 0
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for line in lines:
            amount = line_subtotal(line.quantity, line.unit_price)
            if amount is None:
                unpriced += 1
                continue
            priced += 1
            subtotal += amount
        _check_amount(subtotal, "Subtotal RAB")

        discount = discount_amount(subtotal, adjustments)
        taxable_base = subtotal - discount
        tax = ZERO
        if adjustments.tax_rate_percent is not None:
            tax = round2(taxable_base * adjustments.tax_rate_percent / HUNDRED)
        grand_total = _check_amount(taxable_base + tax, "Grand total")

    return Totals(
        subtotal=subtotal,
        discount_amount=discount,
        taxable_base=taxable_base,
        tax_amount=tax,
        grand_total=grand_total,
        priced_items=priced,
        unpriced_items=unpriced,
    )
