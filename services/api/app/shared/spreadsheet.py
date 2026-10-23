"""Spreadsheet reading for imports and safe cell writing for exports. No database access.

Reading rules (shared by every import):
- Only .csv and .xlsx; the content must match the extension (magic bytes), size and row limits.
- XLSX is opened with openpyxl, which never evaluates formulas; formula cells are flagged so the
  caller can reject them instead of trusting a cached value nobody saw.
- Header names are matched case/space-insensitively against declared columns and aliases.

Writing rule: text from users is never written as a formula (see `write_text`).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openpyxl.cell.cell import Cell as XlsxCell
    from openpyxl.cell.cell import MergedCell

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000


class ImportFileError(ValueError):
    """The file as a whole cannot be imported (format, size, headers)."""


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    required: bool
    aliases: tuple[str, ...] = ()
    hint: str = ""


@dataclass
class Cell:
    value: Any
    is_formula: bool = False


def header_key(text: object) -> str:
    return re.sub(r"[\s\-]+", "_", str(text or "").strip().lower())


def is_blank(cells: Sequence[Cell]) -> bool:
    return all(c.value is None or str(c.value).strip() == "" for c in cells)


# --------------------------------------------------------------------------- readers


def _read_csv(content: bytes) -> Iterator[list[Cell]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    if "\x00" in text:
        raise ImportFileError("File CSV tidak valid (berisi karakter biner).")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    for record in csv.reader(io.StringIO(text), delimiter=delimiter):
        yield [Cell(value) for value in record]


def _read_xlsx(content: bytes, sheet_name: str | None) -> Iterator[list[Cell]]:
    from openpyxl import load_workbook  # local import: only needed for XLSX uploads

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ImportFileError(f"File XLSX tidak dapat dibaca ({type(exc).__name__}).") from None
    try:
        names = workbook.sheetnames
        index = names.index(sheet_name) if sheet_name and sheet_name in names else 0
        sheet = workbook.worksheets[index]
        for row in sheet.iter_rows():
            yield [
                Cell(cell.value, is_formula=getattr(cell, "data_type", None) == "f") for cell in row
            ]
    finally:
        workbook.close()


def read_cells(
    filename: str, content: bytes, *, sheet_name: str | None = None
) -> Iterator[list[Cell]]:
    """Rows of cells from a CSV or XLSX upload (the named sheet if present, else the first)."""
    if len(content) == 0:
        raise ImportFileError("File kosong.")
    if len(content) > MAX_BYTES:
        raise ImportFileError(f"Ukuran file melebihi {MAX_BYTES // (1024 * 1024)} MB.")
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        if not content.startswith(b"PK\x03\x04"):
            raise ImportFileError("File berekstensi .xlsx tetapi isinya bukan XLSX.")
        return _read_xlsx(content, sheet_name)
    if lower.endswith(".csv"):
        if content.startswith(b"PK\x03\x04"):
            raise ImportFileError("File berekstensi .csv tetapi isinya arsip (XLSX?).")
        return _read_csv(content)
    raise ImportFileError("Format tidak didukung. Gunakan .xlsx atau .csv.")


@dataclass
class Table:
    """Header-mapped rows: `rows` yields (spreadsheet row number, {column key: cell})."""

    rows: Iterator[tuple[int, dict[str, Cell]]]
    warnings: list[str]


def read_table(
    filename: str, content: bytes, columns: Sequence[Column], *, sheet_name: str | None = None
) -> Table:
    """Finds the header row, maps it to `columns`, and yields the non-blank data rows."""
    rows_iter = read_cells(filename, content, sheet_name=sheet_name)
    header_cells: list[Cell] | None = None
    header_row = 0
    for header_row, cells in enumerate(rows_iter, start=1):  # noqa: B007 - row number used below
        if not is_blank(cells):
            header_cells = cells
            break
    if header_cells is None:
        raise ImportFileError("File tidak berisi data.")

    lookup = {alias: column for column in columns for alias in (column.header, *column.aliases)}
    warnings: list[str] = []
    positions: dict[str, int] = {}
    for index, cell in enumerate(header_cells):
        key = header_key(cell.value)
        if not key:
            continue
        column = lookup.get(key)
        if column is None:
            warnings.append(f"Kolom '{cell.value}' tidak dikenal dan diabaikan.")
        elif column.key in positions:
            raise ImportFileError(f"Kolom '{column.header}' muncul lebih dari sekali.")
        else:
            positions[column.key] = index
    missing = [c.header for c in columns if c.required and c.key not in positions]
    if missing:
        raise ImportFileError(f"Kolom wajib tidak ditemukan: {', '.join(missing)}.")

    def data_rows() -> Iterator[tuple[int, dict[str, Cell]]]:
        count = 0
        for number, cells in enumerate(rows_iter, start=header_row + 1):
            if is_blank(cells):
                continue
            count += 1
            if count > MAX_ROWS:
                raise ImportFileError(f"Maksimal {MAX_ROWS} baris per impor.")
            yield (
                number,
                {key: cells[i] if i < len(cells) else Cell(None) for key, i in positions.items()},
            )

    return Table(rows=data_rows(), warnings=warnings)


# --------------------------------------------------------------------------- templates


def template_csv(columns: Sequence[Column]) -> bytes:
    return (";".join(c.header for c in columns) + "\r\n").encode("utf-8-sig")


def template_xlsx(columns: Sequence[Column], sheet_name: str, guide: Sequence[str]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.worksheets[0])
    sheet = workbook.create_sheet(sheet_name)
    sheet.append([c.header for c in columns])
    help_sheet = workbook.create_sheet("Petunjuk")
    help_sheet.append(["Kolom", "Wajib", "Keterangan"])
    for column in columns:
        help_sheet.append([column.header, "ya" if column.required else "", column.hint])
    help_sheet.append([])
    for line in guide:
        help_sheet.append([line])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------- safe writing

# Characters that make spreadsheet software treat a cell as a formula (OWASP CSV injection).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def looks_like_formula(value: str) -> bool:
    return value.startswith(FORMULA_PREFIXES)


def write_text(cell: XlsxCell | MergedCell, value: str | None) -> None:
    """Writes user text as a literal string, never as a formula.

    openpyxl turns any string starting with "=" into a formula. Text that looks like a formula is
    stored as an explicit string with Excel's quote-prefix flag, so it shows exactly as typed and
    is not evaluated even if the cell is later edited.
    """
    if value is None:
        cell.value = None
        return
    cell.value = value
    if looks_like_formula(value):
        cell.data_type = "s"
        cell.quotePrefix = True
