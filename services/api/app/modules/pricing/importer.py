"""Row validation for price-catalog imports. No database access.

Safety rules:
- File reading (formats, size/row limits, formula flags) lives in app/shared/spreadsheet.py;
  the uploaded file itself is not stored.
- Any formula cell is rejected so a row cannot smuggle a computed value we did not see.
- Every value is parsed strictly (see parsing.py); bad rows are reported, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.pricing.parsing import (
    CellError,
    parse_date,
    parse_decimal,
    parse_text,
    parse_url,
)
from app.modules.rab.models import RabItemType
from app.shared import spreadsheet
from app.shared.spreadsheet import MAX_BYTES, MAX_ROWS, Cell, Column, ImportFileError

__all__ = ["COLUMNS", "MAX_BYTES", "MAX_ROWS", "ImportFileError", "parse_file"]

SHEET_NAME = "Katalog"


COLUMNS: tuple[Column, ...] = (
    Column("code", "kode", False, ("kode_item", "code"), "Kode item katalog (opsional, unik)"),
    Column("name", "nama", True, ("nama_item", "name", "item"), "Nama barang/jasa"),
    Column("category", "kategori", False, ("category",)),
    Column("brand", "merek", False, ("merk", "brand")),
    Column("specification", "spesifikasi", False, ("spec", "spesifikasi_teknis")),
    Column("unit", "satuan", True, ("unit",), "Mis. m, m3, sak, unit, OH"),
    Column("item_type", "jenis", False, ("type",), "material, tenaga kerja, jasa, peralatan, ..."),
    Column("price", "harga", True, ("harga_satuan", "price"), "Angka tanpa pemisah ribuan"),
    Column("currency", "mata_uang", False, ("currency",), "Default IDR"),
    Column("supplier", "supplier", False, ("vendor", "pemasok")),
    Column("source_reference", "sumber_referensi", False, ("sumber", "referensi")),
    Column("source_url", "sumber_url", False, ("url",)),
    Column("observed_at", "tanggal_harga", True, ("tanggal", "tanggal_sumber"), "YYYY-MM-DD"),
    Column("valid_from", "berlaku_mulai", False),
    Column("valid_until", "berlaku_sampai", False),
    Column("location", "lokasi", False, ("lokasi_pasar",)),
    Column("notes", "catatan", False, ("keterangan",)),
)

ITEM_TYPES: dict[str, RabItemType] = {
    "material": RabItemType.MATERIAL,
    "barang": RabItemType.MATERIAL,
    "material/barang": RabItemType.MATERIAL,
    "tenaga kerja": RabItemType.LABOR,
    "upah": RabItemType.LABOR,
    "labor": RabItemType.LABOR,
    "jasa": RabItemType.SERVICE,
    "service": RabItemType.SERVICE,
    "peralatan": RabItemType.EQUIPMENT,
    "alat": RabItemType.EQUIPMENT,
    "equipment": RabItemType.EQUIPMENT,
    "transportasi": RabItemType.TRANSPORT,
    "transport": RabItemType.TRANSPORT,
    "overhead": RabItemType.OVERHEAD,
    "lain-lain": RabItemType.OTHER,
    "lainnya": RabItemType.OTHER,
    "other": RabItemType.OTHER,
}


@dataclass
class RowResult:
    row: int
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass
class ParsedFile:
    rows: list[RowResult]
    warnings: list[str]


# --------------------------------------------------------------------------- rows


def _parse_row(row_number: int, values: dict[str, Cell]) -> RowResult:
    result = RowResult(row=row_number, data={})
    data = result.data

    def cell(key: str) -> Any:
        found = values.get(key)
        if found is not None and found.is_formula:
            raise CellError(f"Kolom {key} berisi rumus; isi dengan nilai, bukan rumus.")
        return found.value if found is not None else None

    def take(key: str, parse: Any) -> None:
        try:
            data[key] = parse(cell(key))
        except CellError as exc:
            result.errors.append(str(exc))

    take("code", lambda v: parse_text(v, max_length=50, label="Kode"))
    take("name", lambda v: parse_text(v, max_length=300, label="Nama"))
    take("category", lambda v: parse_text(v, max_length=100, label="Kategori"))
    take("brand", lambda v: parse_text(v, max_length=100, label="Merek"))
    take("specification", lambda v: parse_text(v, max_length=5000, label="Spesifikasi"))
    take("unit", lambda v: parse_text(v, max_length=32, label="Satuan"))
    take("supplier", lambda v: parse_text(v, max_length=200, label="Supplier"))
    take("source_reference", lambda v: parse_text(v, max_length=500, label="Sumber referensi"))
    take("source_url", lambda v: parse_url(v, label="Sumber URL"))
    take("location", lambda v: parse_text(v, max_length=100, label="Lokasi"))
    take("notes", lambda v: parse_text(v, max_length=5000, label="Catatan"))

    def price(v: Any) -> str | None:
        amount = parse_decimal(v, max_places=4, label="Harga")
        if amount is not None and amount < 0:
            raise CellError("Harga: tidak boleh negatif.")
        if amount is not None and amount.adjusted() >= 16:
            raise CellError("Harga: melebihi batas nilai.")
        return None if amount is None else str(amount)

    take("price", price)

    def item_type(v: Any) -> str:
        text = parse_text(v, max_length=50, label="Jenis")
        if text is None:
            return RabItemType.MATERIAL.value
        found = ITEM_TYPES.get(text.lower())
        if found is None:
            raise CellError(f"Jenis: '{text}' tidak dikenal.")
        return found.value

    take("item_type", item_type)

    def currency(v: Any) -> str:
        text = parse_text(v, max_length=3, label="Mata uang")
        code = (text or "IDR").upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise CellError("Mata uang: gunakan kode 3 huruf, mis. IDR.")
        return code

    take("currency", currency)

    def iso(label: str) -> Any:
        def parse(v: Any) -> str | None:
            parsed: date | None = parse_date(v, label=label)
            return parsed.isoformat() if parsed else None

        return parse

    take("observed_at", iso("Tanggal harga"))
    take("valid_from", iso("Berlaku mulai"))
    take("valid_until", iso("Berlaku sampai"))

    for key, label in (
        ("name", "Nama"),
        ("unit", "Satuan"),
        ("price", "Harga"),
        ("observed_at", "Tanggal harga"),
    ):
        if data.get(key) is None and not any(e.startswith(label) for e in result.errors):
            result.errors.append(f"{label}: wajib diisi.")
    start = data.get("valid_from") or data.get("observed_at")
    if data.get("valid_until") and start and data["valid_until"] < start:
        result.errors.append("Berlaku sampai: tidak boleh sebelum tanggal berlaku/harga.")
    return result


def parse_file(filename: str, content: bytes) -> ParsedFile:
    table = spreadsheet.read_table(filename, content, COLUMNS, sheet_name=SHEET_NAME)
    rows: list[RowResult] = []
    seen: dict[tuple[Any, ...], int] = {}
    for number, values in table.rows:
        result = _parse_row(number, values)
        if result.valid:
            data = result.data
            identity = (
                (data["code"] or "").lower(),
                data["name"].lower(),
                (data["brand"] or "").lower(),
                (data["specification"] or "").lower(),
                data["unit"].lower(),
                data["price"],
                data["observed_at"],
                (data["supplier"] or "").lower(),
            )
            if identity in seen:
                result.errors.append(f"Duplikat dari baris {seen[identity]}.")
            else:
                seen[identity] = number
        rows.append(result)
    if not rows:
        raise ImportFileError("File tidak berisi baris data.")
    return ParsedFile(rows=rows, warnings=table.warnings)


# --------------------------------------------------------------------------- template


def template_csv() -> bytes:
    return spreadsheet.template_csv(COLUMNS)


def template_xlsx() -> bytes:
    return spreadsheet.template_xlsx(
        COLUMNS,
        SHEET_NAME,
        [
            "Isi data mulai baris 2 sheet 'Katalog'. Jangan gunakan rumus.",
            "Harga tanpa pemisah ribuan (4500 atau 4500,75). Tanggal YYYY-MM-DD atau DD/MM/YYYY.",
            "Harga hasil impor berstatus 'belum terverifikasi' sampai diverifikasi.",
        ],
    )
