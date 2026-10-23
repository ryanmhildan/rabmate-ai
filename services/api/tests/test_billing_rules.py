"""Pure billing rules: term allocation (termin), workflow permissions, invoice/payment state."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.billing.invoicing import (
    PaymentState,
    is_overdue,
    line_amount,
    manual_totals,
    payment_state,
)
from app.modules.billing.models import DocStatus, TermBasis
from app.modules.billing.terms import TermsError, TermSpec, allocate
from app.modules.billing.workflow import Action, allowed_actions
from app.modules.identity.permissions import Permission

D = Decimal
P = TermBasis.PERCENT
A = TermBasis.AMOUNT


def pct(*values: str) -> list[TermSpec]:
    return [TermSpec(f"Termin {i}", P, D(v)) for i, v in enumerate(values, start=1)]


# --------------------------------------------------------------------------- termin


def test_thirty_forty_thirty() -> None:
    # DPP 100.000.000 + PPN 11% = 111.000.000
    terms = allocate(D("100000000.00"), D("11000000.00"), pct("30", "40", "30"))
    assert [t.amount for t in terms] == [D("30000000.00"), D("40000000.00"), D("30000000.00")]
    assert [t.tax_amount for t in terms] == [D("3300000.00"), D("4400000.00"), D("3300000.00")]
    assert [t.total_amount for t in terms] == [D("33300000.00"), D("44400000.00"), D("33300000.00")]
    assert sum(t.total_amount for t in terms) == D("111000000.00")
    assert [t.percent for t in terms] == [D("30"), D("40"), D("30")]


def test_rounding_remainder_goes_to_the_last_term() -> None:
    # The real demo RAB: DPP 12.626.925 + PPN 1.388.961,75 = 14.015.886,75
    dpp, tax = D("12626925.00"), D("1388961.75")
    terms = allocate(dpp, tax, pct("33.33", "33.33", "33.34"))
    assert sum(t.amount for t in terms) == dpp
    assert sum(t.tax_amount for t in terms) == tax
    assert sum(t.total_amount for t in terms) == dpp + tax
    assert terms[0].amount == D("4208554.10")  # round2(12.626.925 x 33,33%)
    assert terms[2].amount == dpp - terms[0].amount - terms[1].amount

    thirds = allocate(D("100.00"), D("0.00"), pct("33.33", "33.33", "33.34"))
    assert [t.amount for t in thirds] == [D("33.33"), D("33.33"), D("33.34")]


def test_fixed_amounts_and_mixed_schedules_must_match_exactly() -> None:
    dpp = D("10000000.00")
    terms = allocate(
        dpp,
        D("1100000.00"),
        [TermSpec("DP", A, D("2500000")), TermSpec("Pelunasan", A, D("7500000"))],
    )
    assert [t.total_amount for t in terms] == [D("2775000.00"), D("8325000.00")]
    assert terms[0].percent is None

    mixed = allocate(
        dpp, D("0.00"), [TermSpec("DP", P, D("30")), TermSpec("Sisa", A, D("7000000"))]
    )
    assert [t.amount for t in mixed] == [D("3000000.00"), D("7000000")]

    with pytest.raises(TermsError, match=r"kurang 1000000\.00"):
        allocate(dpp, D("0"), [TermSpec("DP", P, D("30")), TermSpec("Sisa", A, D("6000000"))])
    with pytest.raises(TermsError, match=r"lebih 1\.00"):
        allocate(dpp, D("0"), [TermSpec("A", A, D("5000001")), TermSpec("B", A, D("5000000"))])


@pytest.mark.parametrize(
    ("specs", "message"),
    [
        (pct("30", "40", "20"), r"Total persentase termin harus 100% \(saat ini 90%\)"),
        (pct("50", "60"), r"saat ini 110%"),
        (pct("0", "100"), "lebih dari 0"),
        (pct("33.333", "66.667"), "maks. 2 desimal"),
        ([TermSpec("X", A, D("-1"))], "lebih dari 0"),
        ([TermSpec("X", A, D("100.001"))], "maks. 2 desimal"),
        ([], "minimal satu termin"),
        (pct(*(["4"] * 25)), "Maksimal 20 termin"),
    ],
)
def test_invalid_schedules_are_refused(specs: list[TermSpec], message: str) -> None:
    with pytest.raises(TermsError, match=message):
        allocate(D("100.00"), D("11.00"), specs)


def test_errors_point_at_the_term() -> None:
    with pytest.raises(TermsError) as caught:
        allocate(D("100.00"), D("0"), pct("50", "0"))
    assert caught.value.index == 1


def test_no_schedule_for_a_zero_contract() -> None:
    with pytest.raises(TermsError, match="lebih dari 0"):
        allocate(D("0.00"), D("0.00"), pct("100"))


def test_single_full_payment() -> None:
    [term] = allocate(D("9711500.00"), D("1068265.00"), pct("100"))
    assert term.total_amount == D("10779765.00")


# --------------------------------------------------------------------------- workflow


def test_workflow_separates_authoring_from_approval() -> None:
    author = frozenset({Permission.FINANCE_WRITE})
    approver = frozenset({Permission.DOCUMENTS_APPROVE})
    write = Permission.FINANCE_WRITE
    assert allowed_actions(DocStatus.DRAFT, author, write=write) == [Action.SUBMIT]
    assert allowed_actions(DocStatus.IN_REVIEW, author, write=write) == [Action.WITHDRAW]
    assert allowed_actions(DocStatus.IN_REVIEW, approver, write=write) == [
        Action.APPROVE,
        Action.REJECT,
    ]
    assert allowed_actions(DocStatus.APPROVED, author, write=write) == [Action.REOPEN]
    assert allowed_actions(DocStatus.REJECTED, author, write=write) == [Action.REOPEN]
    assert allowed_actions(DocStatus.ISSUED, author | approver, write=write) == []
    assert allowed_actions(DocStatus.VOID, author | approver, write=write) == []


# --------------------------------------------------------------------------- invoices


def test_manual_invoice_totals_use_the_rab_rules() -> None:
    assert line_amount(D("2.5"), D("33.335")) == D("83.34")  # ROUND_HALF_UP per line
    totals = manual_totals([(D("1"), D("1000000")), (D("3"), D("250000.50"))], D("11"))
    assert totals.subtotal == D("1750001.50")
    assert totals.tax_amount == D("192500.17")  # round2(1.750.001,50 x 11%)
    assert totals.grand_total == D("1942501.67")
    assert manual_totals([(D("1"), D("100"))], None).tax_amount == D("0.00")


def test_payment_state_and_overdue_come_from_recorded_amounts() -> None:
    total = D("1000.00")
    assert payment_state(DocStatus.DRAFT, total, D("0")) is None
    assert payment_state(DocStatus.ISSUED, total, D("0")) is PaymentState.UNPAID
    assert payment_state(DocStatus.ISSUED, total, D("0.01")) is PaymentState.PARTIAL
    assert payment_state(DocStatus.ISSUED, total, total) is PaymentState.PAID

    today = date(2026, 10, 19)
    assert is_overdue(DocStatus.ISSUED, date(2026, 10, 18), total, D("999.99"), today)
    assert not is_overdue(DocStatus.ISSUED, date(2026, 10, 19), total, D("0"), today)  # due today
    assert not is_overdue(DocStatus.ISSUED, date(2026, 10, 1), total, total, today)  # paid
    assert not is_overdue(DocStatus.VOID, date(2026, 10, 1), total, D("0"), today)
