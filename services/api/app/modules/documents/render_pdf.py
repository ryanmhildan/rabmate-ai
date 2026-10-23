"""RAB document → PDF (ReportLab platypus). Deterministic: the same snapshot gives the same bytes.

Rendering never calculates money: every number printed comes from the snapshot. Shared layout
(letterhead, footer, escaping) lives in pdf_common; the item table and totals here are reused by
the quotation PDF.
"""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, LongTable, Paragraph, Spacer, TableStyle

from app.modules.documents import formatting as fmt
from app.modules.documents.pdf_common import (
    FONT,
    LINE,
    Styles,
    amounts_table,
    build_pdf,
    content_width,
    esc,
    footer_left,
    label_value_table,
    letterhead,
    page_furniture,
    preview_banner,
    signature_block,
    text_sections,
    tint,
)

# Re-exported for callers and tests that import escaping from the RAB renderer.
__all__ = ["esc", "items_table", "render_rab_pdf", "totals_flowables"]


def render_rab_pdf(snapshot: dict[str, Any], verification_code: str | None = None) -> bytes:
    document = snapshot["document"]
    settings = snapshot["settings"]
    rab = snapshot["rab"]
    currency = rab["currency"]
    preview = bool(document["preview"])
    accent = colors.HexColor(settings["accent_color"])
    styles = Styles(accent)
    show_sources = bool(settings["show_price_sources"])
    pagesize = landscape(A4) if show_sources else A4
    width = content_width(pagesize)

    number = document["number"] or "PRATINJAU"
    title = f"{number} — {document['title']}"

    if preview:
        number_line = "<font color='#B42318'><b>PRATINJAU</b></font>"
        when = f"Dibuat {esc(fmt.tanggal_waktu(document['generated_at']))}"
    else:
        number_line = f"<b>{esc(document['number'])}</b>"
        when = f"Tanggal terbit {esc(fmt.tanggal(document['issued_at']))}"
    story: list[Flowable] = letterhead(
        snapshot["company"],
        settings,
        [
            esc(document["title"].upper()),
            number_line,
            when,
            f"{esc(rab['number'])} · versi {rab['version_no']} · {esc(rab['status_label'])}",
        ],
        styles,
        width,
        accent,
    )
    if preview:
        story += preview_banner(
            "PRATINJAU — dokumen belum diterbitkan. Status versi: "
            f"{esc(rab['status_label'])}. Nilai dapat berubah sampai RAB disetujui "
            "dan dokumen diterbitkan.",
            styles,
            width,
        )
    story.append(_info_table(snapshot, styles, width))
    story.append(Spacer(1, 4 * mm))
    story.append(
        items_table(
            snapshot["items"],
            snapshot["groups"],
            currency,
            styles,
            width,
            accent,
            show_codes=bool(settings["show_item_codes"]),
            show_sources=show_sources,
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        KeepTogether(totals_flowables(snapshot["totals"], currency, styles, width, accent))
    )
    story += text_sections(
        (
            ("Catatan", rab["notes"]),
            ("Asumsi", rab["assumptions"]),
            ("Ketentuan", settings["terms"]),
        ),
        styles,
    )
    notes = []
    if rab["approved_at"]:
        notes.append(
            "Persetujuan tercatat secara elektronik di RABmate AI pada "
            f"{fmt.tanggal_waktu(rab['approved_at'])}."
        )
    if not preview:
        notes.append(
            f"Diterbitkan oleh {document['issued_by']} pada "
            f"{fmt.tanggal_waktu(document['issued_at'])}."
        )
    story.append(
        KeepTogether(
            signature_block(
                (
                    ("Disusun oleh", rab["prepared_by"], rab["submitted_at"]),
                    ("Disetujui oleh", rab["approved_by"], rab["approved_at"]),
                ),
                notes,
                styles,
                width,
            )
        )
    )
    return build_pdf(
        story,
        pagesize=pagesize,
        title=title,
        author=snapshot["company"]["legal_name"] or snapshot["company"]["name"],
        subject=f"{rab['number']} versi {rab['version_no']}",
        furniture=page_furniture(
            pagesize=pagesize,
            running_title=title,
            footer_left=footer_left(document["number"], verification_code, preview),
            footer_text=settings["footer_text"],
            preview=preview,
        ),
    )


def _info_table(snapshot: dict[str, Any], styles: Styles, width: float) -> Flowable:
    project = snapshot["project"]
    client = snapshot["client"]
    rab = snapshot["rab"]

    client_text = "—"
    if client:
        parts = [f"<b>{esc(client['name'])}</b>"]
        if client["contact_person"]:
            parts.append(f"u.p. {esc(client['contact_person'])}")
        address = ", ".join(x for x in (client["address"], client["city"]) if x)
        if address:
            parts.append(esc(address))
        client_text = "<br/>".join(parts)
    schedule = "—"
    if project["start_date"] or project["end_date"]:
        schedule = f"{fmt.tanggal(project['start_date'])} s.d. {fmt.tanggal(project['end_date'])}"

    return label_value_table(
        (
            (
                "Proyek",
                f"<b>{esc(project['number'])}</b> — {esc(project['name'])}",
                "Klien",
                client_text,
            ),
            ("Jenis", esc(project["type_label"]), "Lokasi", esc(project["location"] or "—")),
            ("Judul RAB", esc(rab["title"]), "Jadwal", esc(schedule)),
            ("Mata uang", esc(rab["currency"]), "", ""),
        ),
        styles,
        width,
    )


def items_table(
    item_rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    currency: str,
    styles: Styles,
    width: float,
    accent: colors.Color,
    *,
    show_codes: bool,
    show_sources: bool,
) -> LongTable:
    """RAB items grouped by category with subtotal rows; header repeats on every page."""
    items = {item["no"]: item for item in item_rows}

    columns: list[tuple[str, float]] = [("No", 9 * mm)]
    if show_codes:
        columns.append(("Kode", 20 * mm))
    columns.append(("Uraian", 0))
    columns += [
        ("Volume", 18 * mm),
        ("Satuan", 16 * mm),
        ("Harga satuan", 26 * mm),
        ("Jumlah", 29 * mm),
    ]
    if show_sources:
        columns.append(("Sumber harga", 42 * mm))
    fixed = sum(w for _, w in columns)
    widths = [w or (width - fixed) for _, w in columns]
    index = {name: i for i, (name, _) in enumerate(columns)}
    last = len(columns) - 1
    amount_col = index["Jumlah"]

    right_cols = {index["Volume"], index["Harga satuan"], index["Jumlah"]}
    rows: list[list[Any]] = [
        [
            Paragraph(name, styles.th_right if i in right_cols else styles.th)
            for i, (name, _) in enumerate(columns)
        ]
    ]
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    for group in groups:
        if group["title"]:
            rows.append([Paragraph(f"<b>{esc(group['title'])}</b>", styles.cell)] + [""] * last)
            r = len(rows) - 1
            commands += [
                ("SPAN", (0, r), (last, r)),
                ("BACKGROUND", (0, r), (last, r), tint(accent, 0.1)),
            ]
        for no in group["item_numbers"]:
            item = items[no]
            text = f"<b>{esc(item['name'])}</b>"
            if item["specification"]:
                text += f"<br/><font size='7' color='#5F6B7A'>{esc(item['specification'])}</font>"
            row: list[Any] = [str(no)]
            if show_codes:
                row.append(Paragraph(esc(item["code"] or ""), styles.cell))
            row += [
                Paragraph(text, styles.cell),
                Paragraph(fmt.quantity(item["quantity"]), styles.cell_right),
                Paragraph(esc(item["unit"]), styles.cell),
                Paragraph(fmt.unit_price(item["unit_price"], currency), styles.cell_right),
                Paragraph(fmt.money(item["subtotal"], currency), styles.cell_right),
            ]
            if show_sources:
                source = item["price_source_label"] or ""
                if item["price_source"]:
                    source = f"{source}: {item['price_source']}" if source else item["price_source"]
                row.append(Paragraph(f"<font size='7'>{esc(source or '—')}</font>", styles.cell))
            rows.append(row)
        if group["title"]:
            rows.append(
                [Paragraph(f"<b>Subtotal {esc(group['title'])}</b>", styles.cell_right)]
                + [""] * (amount_col - 1)
                + [Paragraph(f"<b>{fmt.money(group['subtotal'], currency)}</b>", styles.cell_right)]
                + [""] * (last - amount_col)
            )
            r = len(rows) - 1
            commands.append(("SPAN", (0, r), (amount_col - 1, r)))
    return LongTable(rows, colWidths=widths, repeatRows=1, style=TableStyle(commands))


def totals_flowables(
    totals: dict[str, Any],
    currency: str,
    styles: Styles,
    width: float,
    accent: colors.Color,
) -> list[Flowable]:
    lines: list[tuple[str, str]] = [("Subtotal", fmt.money(totals["subtotal"], currency))]
    if totals["discount_type"] != "none":
        label = "Diskon"
        if totals["discount_type"] == "percent":
            label = f"Diskon {fmt.percent(totals['discount_value'])}%"
        lines.append((label, "\N{MINUS SIGN} " + fmt.money(totals["discount_amount"], currency)))
    if totals["discount_type"] != "none" or totals["tax_label"]:
        lines.append(("Dasar pengenaan pajak (DPP)", fmt.money(totals["taxable_base"], currency)))
    if totals["tax_label"]:
        lines.append(
            (
                f"{totals['tax_label']} {fmt.percent(totals['tax_rate_percent'])}%",
                fmt.money(totals["tax_amount"], currency),
            )
        )
    out: list[Flowable] = [
        amounts_table(
            lines, ("Total", fmt.money(totals["grand_total"], currency)), styles, width, accent
        )
    ]
    if totals.get("amount_in_words"):
        out += [
            Spacer(1, 2 * mm),
            Paragraph(f"<i>Terbilang: {esc(totals['amount_in_words'])}</i>", styles.right),
        ]
    if totals.get("unpriced_items"):
        out.append(
            Paragraph(
                f"{totals['unpriced_items']} item belum memiliki harga dan tidak dihitung.",
                styles.banner,
            )
        )
    return out
