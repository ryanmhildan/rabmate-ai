"""Pure pricing rules: unit normalization, candidate scoring, spreadsheet cell parsing."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D

import pytest

from app.modules.pricing.matching import Candidate, MatchLevel, Query, numbers, score
from app.modules.pricing.parsing import CellError, parse_date, parse_decimal, parse_text, parse_url
from app.modules.pricing.units import normalize_unit, same_unit

TODAY = date(2026, 10, 19)


# --------------------------------------------------------------------------- units


@pytest.mark.parametrize(
    ("a", "b"),
    [("m³", "M3"), ("Kubik", "m3"), ("zak", "Sak"), ("Lump Sum", "ls"), ("kg.", "Kilogram")],
)
def test_unit_aliases_are_the_same_unit(a: str, b: str) -> None:
    assert same_unit(a, b)


@pytest.mark.parametrize(("a", "b"), [("m", "roll"), ("sak", "kg"), ("unit", "set"), ("m2", "m3")])
def test_different_units_are_never_merged(a: str, b: str) -> None:
    assert not same_unit(a, b)


def test_normalize_unit_trims_and_lowercases() -> None:
    assert normalize_unit("  Meter  ") == "m"


# --------------------------------------------------------------------------- matching


def cand(name: str, unit: str = "m", **kw: object) -> Candidate:
    return Candidate(name=name, unit=unit, verified=True, observed_at=TODAY, **kw)  # type: ignore[arg-type]


def test_identical_item_is_high() -> None:
    result = score(Query("Kabel UTP Cat6", unit="m"), cand("Kabel UTP Cat6"), today=TODAY)
    assert result.level is MatchLevel.HIGH
    assert result.unit_compatible
    assert result.warnings == []


def test_numbers_are_compared_regardless_of_spacing() -> None:
    assert numbers("Kabel Cat 6", "10 mm") == {"6", "10"}
    assert numbers("Besi 2,50 kg") == {"2.5"}
    result = score(Query("Kabel UTP Cat6", unit="m"), cand("Kabel UTP Cat 6"), today=TODAY)
    assert not any("Ukuran" in w for w in result.warnings)


def test_similar_name_with_different_size_is_not_high() -> None:
    result = score(
        Query("Besi beton 10mm", unit="batang"), cand("Besi beton 12mm", unit="batang"), today=TODAY
    )
    assert result.level is not MatchLevel.HIGH
    assert any("10" in w for w in result.warnings)


def test_different_unit_is_capped_low_and_not_applicable() -> None:
    result = score(
        Query("Kabel UTP Cat6", unit="m"), cand("Kabel UTP Cat6", unit="roll"), today=TODAY
    )
    assert result.level is MatchLevel.LOW
    assert not result.unit_compatible
    assert any("Satuan berbeda" in w for w in result.warnings)


def test_brand_mismatch_is_reported() -> None:
    result = score(
        Query("Semen Portland 50kg", unit="sak", brand="Tiga Roda"),
        cand("Semen Portland 50kg", unit="sak", brand="Gresik"),
        today=TODAY,
    )
    assert result.level is MatchLevel.MEDIUM
    assert any("Merek" in w for w in result.warnings)


def test_unverified_stale_and_other_market_are_warned() -> None:
    old = Candidate(
        name="Pasir beton",
        unit="m3",
        location="Surabaya",
        observed_at=date(2025, 1, 2),
        verified=False,
    )
    result = score(Query("Pasir beton", unit="m3", location="Bandung"), old, today=TODAY)
    text = " ".join(result.warnings)
    assert "belum terverifikasi" in text and "6 bulan" in text and "Lokasi" in text


def test_unrelated_item_is_low() -> None:
    assert (
        score(Query("Kabel UTP Cat6"), cand("Cat tembok putih"), today=TODAY).level
        is MatchLevel.LOW
    )


# --------------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4500", D("4500")),
        ("4500.75", D("4500.75")),
        ("4.500,75", D("4500.75")),
        ("1.250.000,5", D("1250000.5")),
        ("4500,75", D("4500.75")),
        ("Rp 65000", D("65000")),
        ("IDR 65000", D("65000")),
        (4500.75, D("4500.75")),
        (65000, D("65000")),
        (0.1, D("0.1")),
        ("0.125", D("0.125")),
    ],
)
def test_parse_decimal_accepts_unambiguous_numbers(raw: object, expected: D) -> None:
    assert parse_decimal(raw, max_places=4, label="Harga") == expected


@pytest.mark.parametrize(
    "raw", ["4.500", "1.250.000", "1,250,000.50", "abc", "1e5", "12,5,3", True]
)
def test_parse_decimal_rejects_ambiguous_or_invalid(raw: object) -> None:
    with pytest.raises(CellError):
        parse_decimal(raw, max_places=4, label="Harga")


def test_parse_decimal_limits_places_and_allows_empty() -> None:
    with pytest.raises(CellError, match="desimal"):
        parse_decimal("1.23456", max_places=4, label="Harga")
    assert parse_decimal("1.2300000", max_places=4, label="Harga") == D("1.2300000")
    assert parse_decimal("  ", max_places=4, label="Harga") is None
    assert parse_decimal(None, max_places=4, label="Harga") is None


def test_parse_date_formats() -> None:
    assert parse_date("2026-10-19", label="Tanggal") == date(2026, 10, 19)
    assert parse_date("19/10/2026", label="Tanggal") == date(2026, 10, 19)
    assert parse_date(datetime(2026, 10, 19, 8, 0), label="Tanggal") == date(2026, 10, 19)
    for bad in ("10/19/2026", "2026/10/19", "kemarin"):
        with pytest.raises(CellError):
            parse_date(bad, label="Tanggal")


def test_parse_text_and_url() -> None:
    assert parse_text("  Kabel   UTP ", max_length=50, label="Nama") == "Kabel UTP"
    assert parse_text(1001.0, max_length=50, label="Kode") == "1001"
    with pytest.raises(CellError):
        parse_text("x" * 51, max_length=50, label="Nama")
    assert parse_url("https://toko.example/kabel", label="URL") == "https://toko.example/kabel"
    for bad in ("javascript:alert(1)", "ftp://x.example", "toko.example"):
        with pytest.raises(CellError):
            parse_url(bad, label="URL")
