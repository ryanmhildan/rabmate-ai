"""Row validation for importing RAB items from a spreadsheet. No database access.

Same safety rules as the catalog import (app/shared/spreadsheet.py): formula cells are rejected,
numbers are parsed strictly (ambiguous "4.500" is an error, never a guess), and bad rows are
reported, not fixed. Line subtotals shown in the preview come from the RAB calculation module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.pricing.importer import ITEM_TYPES
from app.modules.pricing.parsing import CellError, parse_decimal, parse_text
from app.modules.rab.calculation import CalculationError, line_subtotal
from app.modules.rab.models import RabItemType
from app.shared import spreadsheet
from app.shared.spreadsheet import Cell, Column, ImportFileError

SHEET_NAME = "Item RAB"

COLUMNS: tuple[Column, ...] = (
    Column("code", "kode", False, ("kode_item", "code"), "Kode item (opsional)"),
    Column("name", "nama", True, ("nama_item", "uraian", "uraian_pekerjaan", "item", "name")),
    Column("category", "kategori", False, ("kelompok", "category"), "Mis. Pekerjaan persiapan"),
    Column("item_type", "jenis", False, ("type",), "material, tenaga kerja, jasa, peralatan, ..."),
    Column("specification", "spesifikasi", False, ("spec",)),
    Column("quantity", "volume", True, ("kuantitas", "qty", "jumlah_volume"), "Lebih dari 0"),
    Column("unit", "satuan", True, ("unit",), "Mis. m, m3, sak, unit, OH, ls"),
    Column(
        "unit_price",
        "harga_satuan",
        False,
        ("harga", "price", "unit_price"),
        "Opsional; angka tanpa pemisah ribuan",
    ),
    Column("price_source", "sumber_harga", False, ("sumber",), "Mis. nama toko, no. penawaran"),
    Column("notes", "catatan", False, ("keterangan",)),
)

GUIDE = (
    "Isi data mulai baris 2 sheet 'Item RAB'. Jangan gunakan rumus — isi nilai akhirnya.",
    "Volume dan harga ditulis tanpa pemisah ribuan (4500 atau 4500,75); '4.500' ditolak (ambigu).",
    "Harga satuan boleh kosong: item tetap masuk, tetapi RAB belum dapat diajukan sampai diisi.",
    "Item ditambahkan ke versi draft yang dipilih; item yang sudah ada tidak diubah.",
)


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


def _parse_row(number: int, values: dict[str, Cell]) -> RowResult:
    result = RowResult(row=number, data={})
    data = result.data

    def take(key: str, parse: Any) -> None:
        found = values.get(key)
        try:
            if found is not None and found.is_formula:
                raise CellError(f"Kolom {key} berisi rumus; isi dengan nilai, bukan rumus.")
            data[key] = parse(found.value if found is not None else None)
        except CellError as exc:
            result.errors.append(str(exc))

    take("code", lambda v: parse_text(v, max_length=50, label="Kode"))
    take("name", lambda v: parse_text(v, max_length=300, label="Nama"))
    take("category", lambda v: parse_text(v, max_length=100, label="Kategori"))
    take("specification", lambda v: parse_text(v, max_length=10_000, label="Spesifikasi"))
    take("unit", lambda v: parse_text(v, max_length=32, label="Satuan"))
    take("price_source", lambda v: parse_text(v, max_length=500, label="Sumber harga"))
    take("notes", lambda v: parse_text(v, max_length=10_000, label="Catatan"))

    def item_type(v: Any) -> str:
        text = parse_text(v, max_length=50, label="Jenis")
        if text is None:
            return RabItemType.MATERIAL.value
        found = ITEM_TYPES.get(text.lower())
        if found is None:
            raise CellError(f"Jenis: '{text}' tidak dikenal.")
        return found.value

    take("item_type", item_type)

    def quantity(v: Any) -> str | None:
        amount = parse_decimal(v, max_places=4, label="Volume")
        if amount is None:
            return None
        if amount <= 0:
            raise CellError("Volume: harus lebih dari 0.")
        if amount.adjusted() >= 14:
            raise CellError("Volume: melebihi batas nilai.")
        return format(amount, "f")

    def unit_price(v: Any) -> str | None:
        amount = parse_decimal(v, max_places=4, label="Harga satuan")
        if amount is None:
            return None
        if amount < 0:
            raise CellError("Harga satuan: tidak boleh negatif.")
        if amount.adjusted() >= 16:
            raise CellError("Harga satuan: melebihi batas nilai.")
        return format(amount, "f")

    take("quantity", quantity)
    take("unit_price", unit_price)

    for key, label in (("name", "Nama"), ("quantity", "Volume"), ("unit", "Satuan")):
        if data.get(key) is None and not any(e.startswith(label) for e in result.errors):
            result.errors.append(f"{label}: wajib diisi.")

    data["subtotal"] = None
    if result.valid and data["unit_price"] is not None:
        try:
            subtotal = line_subtotal(Decimal(data["quantity"]), Decimal(data["unit_price"]))
        except CalculationError as exc:
            result.errors.append(exc.message)
        else:
            data["subtotal"] = format(subtotal, "f") if subtotal is not None else None
    return result


def parse_file(filename: str, content: bytes) -> ParsedFile:
    table = spreadsheet.read_table(filename, content, COLUMNS, sheet_name=SHEET_NAME)
    rows: list[RowResult] = []
    seen: dict[tuple[Any, ...], int] = {}
    for number, values in table.rows:
        result = _parse_row(number, values)
        if result.valid:
            identity = tuple(
                (result.data.get(c.key) or "").lower()
                if isinstance(result.data.get(c.key), str)
                else result.data.get(c.key)
                for c in COLUMNS
            )
            if identity in seen:
                result.errors.append(f"Duplikat dari baris {seen[identity]}.")
            else:
                seen[identity] = number
        rows.append(result)
    if not rows:
        raise ImportFileError("File tidak berisi baris data.")
    return ParsedFile(rows=rows, warnings=table.warnings)


def template_csv() -> bytes:
    return spreadsheet.template_csv(COLUMNS)


def template_xlsx() -> bytes:
    return spreadsheet.template_xlsx(COLUMNS, SHEET_NAME, GUIDE)
