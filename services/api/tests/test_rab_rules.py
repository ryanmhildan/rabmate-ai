"""RAB validation rules and version comparison (pure, no database)."""

from __future__ import annotations

import uuid
from decimal import Decimal as D

from app.modules.rab.calculation import Adjustments, DiscountType
from app.modules.rab.compare import ChangeKind, CompareItem, compare_items
from app.modules.rab.validation import ItemFacts, Severity, has_errors, validate


def facts(
    name: str = "Item",
    *,
    price: str | None = "1000",
    code: str | None = None,
    source: str | None = "Manual",
    quantity: str = "1",
    position: int = 1,
) -> ItemFacts:
    return ItemFacts(
        id=uuid.uuid4(),
        position=position,
        code=code,
        name=name,
        quantity=D(quantity),
        unit_price=D(price) if price is not None else None,
        price_source=source,
    )


def codes(issues: list) -> set[str]:  # type: ignore[type-arg]
    return {issue.code for issue in issues}


TAX = Adjustments(tax_rate_percent=D("11"))


def test_empty_rab_is_an_error() -> None:
    issues = validate([], TAX, "PPN")
    assert "empty" in codes(issues)
    assert has_errors(issues)


def test_missing_price_blocks_submission_and_points_at_item() -> None:
    item = facts("Semen", price=None)
    issues = validate([item], TAX, "PPN")
    missing = [i for i in issues if i.code == "missing_price"]
    assert missing and missing[0].item_id == item.id and missing[0].severity is Severity.ERROR
    assert has_errors(issues)


def test_warnings_do_not_block() -> None:
    issues = validate(
        [facts("Gratis", price="0", code="A"), facts("Tanpa sumber", source=" ", code="a")],
        TAX,
        "PPN",
    )
    assert {"zero_price", "missing_price_source", "duplicate_code"} <= codes(issues)
    assert not has_errors(issues)


def test_discount_exceeding_subtotal_is_an_error() -> None:
    adjustments = Adjustments(DiscountType.AMOUNT, D("5000"), D("11"))
    issues = validate([facts(price="1000")], adjustments, "PPN")
    assert "discount_exceeds_subtotal" in codes(issues)
    assert has_errors(issues)


def test_missing_tax_is_informational_only() -> None:
    issues = validate([facts()], Adjustments(), None)
    assert [i.severity for i in issues if i.code == "no_tax"] == [Severity.INFO]
    assert not has_errors(issues)


def test_valid_rab_has_no_issues_beyond_info() -> None:
    assert validate([facts(code="A1"), facts("B", code="B1")], TAX, "PPN") == []


# --------------------------------------------------------------------------- compare


def item(
    name: str,
    *,
    code: str | None = None,
    qty: str = "1",
    price: str | None = "100",
    unit: str = "unit",
) -> CompareItem:
    unit_price = D(price) if price is not None else None
    subtotal = (D(qty) * unit_price).quantize(D("0.01")) if unit_price is not None else None
    return CompareItem(code, name, unit, D(qty), unit_price, subtotal, "material")


def test_compare_detects_added_removed_changed_unchanged() -> None:
    before = [item("Semen", code="M1", qty="10"), item("Pasir", unit="m3"), item("Cat")]
    after = [item("Semen Portland", code="m1", qty="12"), item("Pasir", unit="m3"), item("Besi")]

    changes = {c.key: c for c in compare_items(before, after)}

    semen = changes["code:m1"]
    assert semen.kind is ChangeKind.CHANGED
    assert set(semen.changed_fields) == {"name", "quantity"}
    assert semen.subtotal_delta == D("200.00")
    assert changes["name:pasir|m3"].kind is ChangeKind.UNCHANGED
    assert changes["name:besi|unit"].kind is ChangeKind.ADDED
    assert changes["name:cat|unit"].kind is ChangeKind.REMOVED
    assert changes["name:cat|unit"].subtotal_delta == D("-100.00")


def test_compare_handles_repeated_names_deterministically() -> None:
    before = [item("Baut", price="10"), item("Baut", price="20")]
    after = [item("Baut", price="10"), item("Baut", price="25"), item("Baut", price="30")]

    kinds = [c.kind for c in compare_items(before, after)]

    assert kinds == [ChangeKind.UNCHANGED, ChangeKind.CHANGED, ChangeKind.ADDED]


def test_compare_price_appearing_counts_as_change() -> None:
    changes = compare_items([item("Kabel", price=None)], [item("Kabel", price="5000")])
    assert changes[0].changed_fields == ["unit_price"]
    assert changes[0].subtotal_delta == D("5000.00")


def test_case_only_rename_matches_same_item_but_reports_change() -> None:
    changes = compare_items([item("Pasir", unit="m3")], [item("pasir", unit="M3")])
    assert len(changes) == 1
    assert changes[0].kind is ChangeKind.CHANGED
    assert set(changes[0].changed_fields) == {"name", "unit"}
