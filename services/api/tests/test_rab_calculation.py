"""RAB arithmetic. No database: these run in the DB-free test selection too."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.modules.rab.calculation import (
    MAX_AMOUNT,
    Adjustments,
    CalculationError,
    DiscountType,
    LineInput,
    calculate,
    line_subtotal,
    round2,
)


def lines(*pairs: tuple[str, str | None]) -> list[LineInput]:
    return [LineInput(D(q), D(p) if p is not None else None) for q, p in pairs]


# --------------------------------------------------------------------------- lines & rounding


@pytest.mark.parametrize(
    ("quantity", "price", "expected"),
    [
        ("3", "33.335", "100.01"),  # 100.005 rounds half UP, not to even
        ("1", "0.005", "0.01"),
        ("1", "0.004", "0.00"),
        ("2.5", "1000", "2500.00"),
        ("0.0001", "1", "0.00"),
        ("12.3456", "7890.1234", "97408.31"),  # exact product 97408.30744704
    ],
)
def test_line_subtotal_rounds_half_up(quantity: str, price: str, expected: str) -> None:
    assert line_subtotal(D(quantity), D(price)) == D(expected)


def test_round2_is_half_up_for_negative_and_positive() -> None:
    assert round2(D("2.345")) == D("2.35")
    assert round2(D("-2.345")) == D("-2.35")


def test_unpriced_line_has_no_subtotal() -> None:
    assert line_subtotal(D("5"), None) is None


def test_values_near_the_column_limit_stay_exact() -> None:
    # (10^10 - 10^-4)(10^8 - 10^-4) = 10^18 - 10^6 - 10^4 + 10^-8, just under MAX_AMOUNT.
    quantity, price = D("9999999999.9999"), D("99999999.9999")
    assert line_subtotal(quantity, price) == D("999999999998990000.00")


def test_overflow_is_reported_not_truncated() -> None:
    with pytest.raises(CalculationError) as exc:
        line_subtotal(D("99999999999999.9999"), D("9999999999999999.9999"))
    assert exc.value.code == "amount_overflow"
    with pytest.raises(CalculationError):
        calculate(lines((str(MAX_AMOUNT), "1"), ("1", "1")), Adjustments())


# --------------------------------------------------------------------------- totals


def test_subtotal_is_sum_of_rounded_lines() -> None:
    # Each line rounds first: 0.005→0.01 twice = 0.02 (not round(0.010)=0.01).
    totals = calculate(lines(("1", "0.005"), ("1", "0.005")), Adjustments())
    assert totals.subtotal == D("0.02")
    assert totals.grand_total == D("0.02")


def test_no_tax_and_no_discount_when_not_configured() -> None:
    totals = calculate(lines(("10", "15000"), ("2", "250000")), Adjustments())
    assert totals.subtotal == D("650000.00")
    assert totals.discount_amount == D("0.00")
    assert totals.tax_amount == D("0.00")
    assert totals.grand_total == D("650000.00")


def test_tax_is_applied_after_discount() -> None:
    adjustments = Adjustments(DiscountType.PERCENT, D("10"), D("11"))
    totals = calculate(lines(("1", "1000000")), adjustments)
    assert totals.discount_amount == D("100000.00")
    assert totals.taxable_base == D("900000.00")
    assert totals.tax_amount == D("99000.00")
    assert totals.grand_total == D("999000.00")


def test_fixed_discount_and_tax_rounding() -> None:
    adjustments = Adjustments(DiscountType.AMOUNT, D("333.333"), D("11"))
    totals = calculate(lines(("1", "10000")), adjustments)
    assert totals.discount_amount == D("333.33")
    assert totals.taxable_base == D("9666.67")
    assert totals.tax_amount == D("1063.33")  # 1063.3337 → 1063.33
    assert totals.grand_total == D("10730.00")


def test_discount_larger_than_subtotal_is_rejected() -> None:
    with pytest.raises(CalculationError) as exc:
        calculate(lines(("1", "100")), Adjustments(DiscountType.AMOUNT, D("100.01")))
    assert exc.value.code == "discount_exceeds_subtotal"


@pytest.mark.parametrize("value", ["-1", "100.01"])
def test_percent_discount_bounds(value: str) -> None:
    with pytest.raises(CalculationError):
        calculate(lines(("1", "100")), Adjustments(DiscountType.PERCENT, D(value)))


def test_full_discount_is_allowed() -> None:
    totals = calculate(lines(("1", "100")), Adjustments(DiscountType.PERCENT, D("100"), D("11")))
    assert totals.grand_total == D("0.00")


def test_unpriced_items_are_counted_but_excluded() -> None:
    totals = calculate(lines(("2", "500"), ("3", None)), Adjustments())
    assert totals.subtotal == D("1000.00")
    assert (totals.priced_items, totals.unpriced_items) == (1, 1)


def test_empty_rab_totals_zero() -> None:
    totals = calculate([], Adjustments(tax_rate_percent=D("11")))
    assert totals.grand_total == D("0.00")
    assert totals.priced_items == 0


def test_amounts_have_exactly_two_decimals() -> None:
    totals = calculate(lines(("1", "1")), Adjustments(DiscountType.PERCENT, D("0"), D("0")))
    for value in (totals.subtotal, totals.discount_amount, totals.tax_amount, totals.grand_total):
        assert value.as_tuple().exponent == -2
