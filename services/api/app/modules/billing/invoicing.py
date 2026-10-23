"""Invoice arithmetic and payment status. Pure functions.

Manual invoice totals reuse the RAB calculation module (round2 per line, tax on the subtotal),
so there is exactly one implementation of the money rules. Payment status is derived from the
amount recorded as paid — never from a claim (ADR-036).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.modules.billing.models import DocStatus
from app.modules.rab.calculation import Adjustments, LineInput, calculate, line_subtotal

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class InvoiceTotals:
    subtotal: Decimal
    tax_amount: Decimal
    grand_total: Decimal


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    amount = line_subtotal(quantity, unit_price)
    if amount is None:  # unreachable: invoice lines always carry a unit price
        raise ValueError("unit_price wajib")
    return amount


def manual_totals(
    lines: list[tuple[Decimal, Decimal]], tax_rate_percent: Decimal | None
) -> InvoiceTotals:
    totals = calculate(
        (LineInput(quantity, price) for quantity, price in lines),
        Adjustments(tax_rate_percent=tax_rate_percent),
    )
    return InvoiceTotals(totals.subtotal, totals.tax_amount, totals.grand_total)


class PaymentState(StrEnum):
    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"


def payment_state(
    status: DocStatus, grand_total: Decimal, amount_paid: Decimal
) -> PaymentState | None:
    """None until the invoice is issued (drafts are not receivables)."""
    if status is not DocStatus.ISSUED:
        return None
    if amount_paid <= 0:
        return PaymentState.UNPAID
    if amount_paid < grand_total:
        return PaymentState.PARTIAL
    return PaymentState.PAID


def is_overdue(
    status: DocStatus,
    due_date: date | None,
    grand_total: Decimal,
    amount_paid: Decimal,
    today: date,
) -> bool:
    return (
        status is DocStatus.ISSUED
        and due_date is not None
        and amount_paid < grand_total
        and due_date < today
    )
