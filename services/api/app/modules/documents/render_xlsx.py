"""RAB document → XLSX (openpyxl). Values only — the workbook contains no formulas.

Totals are the server's figures, written as numbers so the sheet stays usable for analysis. A
value that a spreadsheet number (IEEE double) cannot hold exactly is written as text instead of
being silently rounded. User text goes through `write_text`, so nothing can become a formula.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from app.modules.documents import formatting as fmt
from app.shared.spreadsheet import write_text

THIN = Side(style="thin", color="C9D1DB")
GREY = "5F6B7A"
DANGER = "B42318"


def _excel_number(value: str | None) -> int | float | str | None:
    """Exact spreadsheet number for a decimal string, or the string itself if not representable."""
    if value is None:
        return None
    amount = Decimal(value)
    if amount == amount.to_integral_value() and abs(amount) < 2**53:
        return int(amount)
    as_float = float(amount)
    if Decimal(repr(as_float)) == amount.normalize():
        return as_float
    return value


def _number_format(value: str | None, places: int) -> str:
    if value is None:
        return "General"
    amount = Decimal(value)
    if amount == amount.to_integral_value():
        return "#,##0" if places == 0 else "#,##0." + "0" * places
    return "#,##0." + "0" * places + "#" * max(0, 4 - places)


def _tint(hex_color: str, amount: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    mix = [round(255 - (255 - c) * amount) for c in (r, g, b)]
    return "".join(f"{c:02X}" for c in mix)


def _naive_utc(value: str | None) -> datetime:
    moment = datetime.fromisoformat(value) if value else datetime(2000, 1, 1, tzinfo=UTC)
    return moment.astimezone(UTC).replace(tzinfo=None)


def render_rab_xlsx(snapshot: dict[str, Any], verification_code: str | None = None) -> bytes:
    document = snapshot["document"]
    settings = snapshot["settings"]
    rab = snapshot["rab"]
    company = snapshot["company"]
    accent = settings["accent_color"].lstrip("#").upper()
    preview = bool(document["preview"])

    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "RAB"

    def text(row: int, col: int, value: str | None, **style: Any) -> None:
        cell = sheet.cell(row=row, column=col)
        write_text(cell, value)
        for key, val in style.items():
            setattr(cell, key, val)

    show_codes = bool(settings["show_item_codes"])
    show_sources = bool(settings["show_price_sources"])
    headers = ["No"] + (["Kode"] if show_codes else []) + ["Uraian", "Spesifikasi", "Kategori"]
    headers += ["Volume", "Satuan", "Harga satuan", "Jumlah"]
    if show_sources:
        headers += ["Jenis sumber", "Sumber harga"]
    col = {name: i for i, name in enumerate(headers, start=1)}
    width = len(headers)

    row = 1
    text(row, 1, company["legal_name"] or company["name"], font=Font(bold=True, size=14))
    if settings["tagline"]:
        row += 1
        text(row, 1, settings["tagline"], font=Font(italic=True, color=GREY))
    row += 1
    text(row, 1, document["title"].upper(), font=Font(bold=True, size=12, color=accent))
    row += 1
    if preview:
        text(
            row,
            1,
            f"PRATINJAU: belum diterbitkan (status versi: {rab['status_label']}). "
            "Nilai dapat berubah.",
            font=Font(bold=True, color=DANGER),
        )
    else:
        text(row, 1, f"Nomor dokumen: {document['number']}", font=Font(bold=True))
        row += 1
        text(row, 1, f"Tanggal terbit: {fmt.tanggal(document['issued_at'])}")

    project = snapshot["project"]
    client = snapshot["client"]
    info = [
        ("Proyek", f"{project['number']} · {project['name']}"),
        ("Klien", client["name"] if client else "-"),
        ("Lokasi", project["location"] or "-"),
        ("Judul RAB", rab["title"]),
        ("RAB / versi", f"{rab['number']} versi {rab['version_no']} ({rab['status_label']})"),
        ("Mata uang", rab["currency"]),
    ]
    row += 1
    for label, value in info:
        row += 1
        text(row, 1, label, font=Font(color=GREY))
        text(row, 3, value)

    row += 2
    header_row = row
    for name, index in col.items():
        text(
            row,
            index,
            name,
            font=Font(bold=True, color="FFFFFF"),
            fill=PatternFill("solid", fgColor=accent),
            alignment=Alignment(vertical="center", wrap_text=True),
        )

    items = {item["no"]: item for item in snapshot["items"]}
    group_fill = PatternFill("solid", fgColor=_tint(settings["accent_color"], 0.12))
    for group in snapshot["groups"]:
        if group["title"]:
            row += 1
            text(row, col["Uraian"], group["title"], font=Font(bold=True))
            for c in range(1, width + 1):
                sheet.cell(row=row, column=c).fill = group_fill
        for no in group["item_numbers"]:
            item = items[no]
            row += 1
            sheet.cell(row=row, column=col["No"], value=no)
            if show_codes:
                text(row, col["Kode"], item["code"])
            text(row, col["Uraian"], item["name"], alignment=Alignment(wrap_text=True))
            text(
                row, col["Spesifikasi"], item["specification"], alignment=Alignment(wrap_text=True)
            )
            text(row, col["Kategori"], item["category"])
            for name, key, places in (
                ("Volume", "quantity", 0),
                ("Harga satuan", "unit_price", 0),
                ("Jumlah", "subtotal", 2),
            ):
                cell = sheet.cell(row=row, column=col[name], value=_excel_number(item[key]))
                cell.number_format = _number_format(item[key], places)
                if item[key] is None:
                    write_text(cell, "-")
            text(row, col["Satuan"], item["unit"])
            if show_sources:
                text(row, col["Jenis sumber"], item["price_source_label"])
                text(row, col["Sumber harga"], item["price_source"])
        if group["title"]:
            row += 1
            text(row, col["Harga satuan"], f"Subtotal {group['title']}", font=Font(bold=True))
            cell = sheet.cell(row=row, column=col["Jumlah"], value=_excel_number(group["subtotal"]))
            cell.number_format = "#,##0.00"
            cell.font = Font(bold=True)
    last_item_row = row
    for r in range(header_row, last_item_row + 1):
        for c in range(1, width + 1):
            sheet.cell(row=r, column=c).border = Border(bottom=THIN)
            if sheet.cell(row=r, column=c).alignment.vertical is None:
                sheet.cell(row=r, column=c).alignment = Alignment(
                    vertical="top", wrap_text=sheet.cell(row=r, column=c).alignment.wrap_text
                )

    totals = snapshot["totals"]
    currency = rab["currency"]
    lines: list[tuple[str, str]] = [("Subtotal", totals["subtotal"])]
    if totals["discount_type"] != "none":
        label = "Diskon"
        if totals["discount_type"] == "percent":
            label = f"Diskon {fmt.percent(totals['discount_value'])}%"
        lines.append((label, f"-{totals['discount_amount']}"))
    if totals["discount_type"] != "none" or totals["tax_label"]:
        lines.append(("Dasar pengenaan pajak (DPP)", totals["taxable_base"]))
    if totals["tax_label"]:
        lines.append(
            (
                f"{totals['tax_label']} {fmt.percent(totals['tax_rate_percent'])}%",
                totals["tax_amount"],
            )
        )
    lines.append((f"Total ({currency})", totals["grand_total"]))
    row += 1
    for index, (label, value) in enumerate(lines):
        row += 1
        bold = index == len(lines) - 1
        text(row, col["Harga satuan"], label, font=Font(bold=bold))
        cell = sheet.cell(row=row, column=col["Jumlah"], value=_excel_number(value))
        cell.number_format = "#,##0.00"
        cell.font = Font(bold=bold)
    if totals["amount_in_words"]:
        row += 1
        text(
            row,
            col["Harga satuan"],
            f"Terbilang: {totals['amount_in_words']}",
            font=Font(italic=True),
        )
    if totals["unpriced_items"]:
        row += 1
        text(
            row,
            col["Harga satuan"],
            f"{totals['unpriced_items']} item belum memiliki harga dan tidak dihitung.",
            font=Font(color=DANGER),
        )

    for title, body in (
        ("Catatan", rab["notes"]),
        ("Asumsi", rab["assumptions"]),
        ("Ketentuan", settings["terms"]),
    ):
        if body:
            row += 2
            text(row, 1, title, font=Font(bold=True))
            row += 1
            text(row, 1, body, alignment=Alignment(wrap_text=True, vertical="top"))
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
            sheet.row_dimensions[row].height = min(
                400, 15 * (body.count("\n") + 1 + len(body) // 120)
            )

    widths = {"No": 5, "Kode": 14, "Uraian": 40, "Spesifikasi": 32, "Kategori": 18, "Volume": 11}
    widths |= {"Satuan": 9, "Harga satuan": 18, "Jumlah": 20, "Jenis sumber": 16}
    widths |= {"Sumber harga": 40}
    for name, index in col.items():
        sheet.column_dimensions[get_column_letter(index)].width = widths[name]
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.print_title_rows = f"{header_row}:{header_row}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)

    _info_sheet(workbook.create_sheet("Info"), snapshot, verification_code)

    stamp = _naive_utc(document["issued_at"] or document["generated_at"])
    workbook.properties.creator = "RABmate AI"
    workbook.properties.title = f"{document['number'] or 'PRATINJAU'} · {document['title']}"
    workbook.properties.created = stamp
    workbook.properties.modified = stamp
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _info_sheet(sheet: Worksheet, snapshot: dict[str, Any], verification_code: str | None) -> None:
    document = snapshot["document"]
    rab = snapshot["rab"]
    rows = [
        ("Nomor dokumen", document["number"] or "PRATINJAU: belum diterbitkan"),
        ("Jenis", document["title"]),
        ("RAB", f"{rab['number']} versi {rab['version_no']}"),
        ("Status versi", rab["status_label"]),
        ("Disetujui oleh", rab["approved_by"] or "-"),
        ("Disetujui pada", fmt.tanggal_waktu(rab["approved_at"]) if rab["approved_at"] else "-"),
        ("Diterbitkan oleh", document["issued_by"] or "-"),
        (
            "Diterbitkan pada",
            fmt.tanggal_waktu(document["issued_at"]) if document["issued_at"] else "-",
        ),
        ("Kode verifikasi (SHA-256 snapshot)", verification_code or "-"),
        ("Versi skema snapshot", str(snapshot["schema_version"])),
        ("Keterangan", "Nilai dihitung oleh server RABmate AI. Berkas ini tidak berisi rumus."),
    ]
    for index, (label, value) in enumerate(rows, start=1):
        write_text(sheet.cell(row=index, column=1), label)
        sheet.cell(row=index, column=1).font = Font(bold=True)
        write_text(sheet.cell(row=index, column=2), value)
    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 80
