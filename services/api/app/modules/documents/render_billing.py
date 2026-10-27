"""Quotation and invoice PDFs from their snapshots (layout shared with the RAB PDF).

Same rules as every document: values come from the snapshot only, user text is escaped, no
signatures are drawn, and wording added by the template is neutral (no legal clauses).
"""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    LongTable,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

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
    letterhead_image,
    page_furniture,
    preview_banner,
    signature_block,
    text_sections,
    tint,
)
from app.modules.documents.render_pdf import items_table, totals_flowables


def client_markup(client: dict[str, Any] | None, *, with_tax_id: bool = False) -> str:
    if not client:
        return "-"
    parts = [f"<b>{esc(client['name'])}</b>"]
    if client.get("contact_person"):
        parts.append(f"u.p. {esc(client['contact_person'])}")
    address = ", ".join(x for x in (client.get("address"), client.get("city")) if x)
    if address:
        parts.append(esc(address))
    if with_tax_id and client.get("tax_id"):
        parts.append(f"NPWP {esc(client['tax_id'])}")
    return "<br/>".join(parts)


def approval_notes(record: dict[str, Any], document: dict[str, Any]) -> list[str]:
    notes = []
    if record["approved_at"]:
        notes.append(
            "Persetujuan tercatat secara elektronik di RABmate AI pada "
            f"{fmt.tanggal_waktu(record['approved_at'])}."
        )
    if not document["preview"]:
        notes.append(
            f"Diterbitkan oleh {document['issued_by']} pada "
            f"{fmt.tanggal_waktu(document['issued_at'])}."
        )
    return notes


def grid_table(rows: list[list[Any]], widths: list[float], accent: colors.Color) -> LongTable:
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    return LongTable(rows, colWidths=widths, repeatRows=1, style=TableStyle(commands))


# --------------------------------------------------------------------------- quotation


def render_quotation_pdf(
    snapshot: dict[str, Any],
    verification_code: str | None = None,
    letterhead_png: bytes | None = None,
) -> bytes:
    document = snapshot["document"]
    settings = snapshot["settings"]
    quotation = snapshot["quotation"]
    currency = snapshot["currency"]
    preview = bool(document["preview"])
    accent = colors.HexColor(settings["accent_color"])
    styles = Styles(accent)
    pagesize = A4
    width = content_width(pagesize)
    number = quotation["number"]
    title = f"{number} · {document['title']}"

    when = (
        f"Dibuat {esc(fmt.tanggal_waktu(document['generated_at']))}"
        if preview
        else f"Tanggal {esc(fmt.tanggal(document['issued_at']))}"
    )
    right = [
        esc(document["title"].upper()),
        (
            f"<font color='#B42318'><b>PRATINJAU</b></font> · {esc(number)}"
            if preview
            else f"<b>{esc(number)}</b>"
        ),
        when,
    ]
    if quotation["valid_until"]:
        right.append(f"Berlaku sampai {esc(fmt.tanggal(quotation['valid_until']))}")
    image = letterhead_image(settings, letterhead_png)
    story: list[Flowable] = letterhead(
        snapshot["company"], settings, right, styles, width, accent, image=image
    )
    if preview:
        story += preview_banner(
            f"PRATINJAU: penawaran belum diterbitkan. Status: {esc(quotation['status_label'])}.",
            styles,
            width,
        )
    project = snapshot["project"]
    story.append(
        label_value_table(
            (
                (
                    "Kepada",
                    client_markup(snapshot["client"]),
                    "Perihal",
                    f"<b>{esc(quotation['subject'])}</b>",
                ),
                (
                    "Proyek",
                    f"{esc(project['number'])} · {esc(project['name'])}",
                    "Referensi",
                    f"{esc(quotation['rab_number'])} versi {quotation['rab_version_no']}",
                ),
            ),
            styles,
            width,
        )
    )
    story.append(Spacer(1, 4 * mm))
    intro = quotation["introduction"] or (
        "Bersama ini kami sampaikan penawaran harga dengan rincian sebagai berikut."
    )
    story.append(Paragraph(esc(intro), styles.body))
    story += text_sections((("Lingkup pekerjaan", quotation["scope"]),), styles)
    story.append(Spacer(1, 3 * mm))
    story.append(
        items_table(
            snapshot["items"],
            snapshot["groups"],
            currency,
            styles,
            width,
            accent,
            show_codes=bool(settings["show_item_codes"]),
            show_sources=False,  # price provenance is internal; never printed on an offer
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        KeepTogether(totals_flowables(snapshot["totals"], currency, styles, width, accent))
    )
    if snapshot["payment_terms"]:
        story.append(Paragraph("Jadwal pembayaran", styles.heading))
        story.append(terms_table(snapshot["payment_terms"], currency, styles, width, accent))
    sections = [("Ketentuan", quotation["terms"]), ("Catatan", quotation["notes"])]
    story += text_sections(sections, styles)
    if quotation["valid_until"]:
        story.append(Spacer(1, 2 * mm))
        story.append(
            Paragraph(
                f"Penawaran ini berlaku sampai {esc(fmt.tanggal(quotation['valid_until']))}.",
                styles.body,
            )
        )
    story.append(
        KeepTogether(
            signature_block(
                (
                    ("Disusun oleh", quotation["prepared_by"], quotation["submitted_at"]),
                    ("Disetujui oleh", quotation["approved_by"], quotation["approved_at"]),
                ),
                approval_notes(quotation, document),
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
        subject=quotation["subject"],
        furniture=page_furniture(
            pagesize=pagesize,
            running_title=title,
            footer_left=footer_left(number, verification_code, preview),
            footer_text=settings["footer_text"],
            preview=preview,
        ),
    )


def terms_table(
    terms: list[dict[str, Any]], currency: str, styles: Styles, width: float, accent: colors.Color
) -> LongTable:
    headers = [
        "No",
        "Termin",
        "Porsi",
        "Sebelum pajak",
        "Pajak",
        "Total",
        "Jatuh tempo / keterangan",
    ]
    widths = [9 * mm, 0.0, 14 * mm, 30 * mm, 26 * mm, 32 * mm, 30 * mm]
    widths[1] = width - sum(widths)
    rows: list[list[Any]] = [
        [
            Paragraph(h, styles.th_right if i in {2, 3, 4, 5} else styles.th)
            for i, h in enumerate(headers)
        ]
    ]
    for term in terms:
        portion = f"{fmt.percent(term['percent'])}%" if term["percent"] else "Nilai tetap"
        info = []
        if term["due_date"]:
            info.append(fmt.tanggal(term["due_date"]))
        if term["description"]:
            info.append(term["description"])
        rows.append(
            [
                str(term["no"]),
                Paragraph(f"<b>{esc(term['name'])}</b>", styles.cell),
                Paragraph(esc(portion), styles.cell_right),
                Paragraph(fmt.money(term["amount"], currency), styles.cell_right),
                Paragraph(fmt.money(term["tax_amount"], currency), styles.cell_right),
                Paragraph(f"<b>{fmt.money(term['total_amount'], currency)}</b>", styles.cell_right),
                Paragraph(esc(" · ".join(info) or "-"), styles.cell),
            ]
        )
    return grid_table(rows, widths, accent)


# --------------------------------------------------------------------------- invoice


def render_invoice_pdf(
    snapshot: dict[str, Any],
    verification_code: str | None = None,
    letterhead_png: bytes | None = None,
) -> bytes:
    document = snapshot["document"]
    settings = snapshot["settings"]
    invoice = snapshot["invoice"]
    totals = snapshot["totals"]
    currency = snapshot["currency"]
    preview = bool(document["preview"])
    accent = colors.HexColor(settings["accent_color"])
    styles = Styles(accent)
    pagesize = A4
    width = content_width(pagesize)
    number = document["number"]
    title = f"{number or 'PRATINJAU'} · {document['title']}"

    right = [
        esc(document["title"].upper()),
        "<font color='#B42318'><b>PRATINJAU</b></font>" if preview else f"<b>{esc(number)}</b>",
        f"Tanggal {esc(fmt.tanggal(invoice['issue_date']))}"
        if invoice["issue_date"]
        else "Belum diterbitkan",
        f"Jatuh tempo <b>{esc(fmt.tanggal(invoice['due_date']))}</b>"
        if invoice["due_date"]
        else "Jatuh tempo -",
    ]
    image = letterhead_image(settings, letterhead_png)
    story: list[Flowable] = letterhead(
        snapshot["company"], settings, right, styles, width, accent, image=image
    )
    if preview:
        story += preview_banner(
            "PRATINJAU: invoice belum diterbitkan dan belum bernomor. Status: "
            f"{esc(invoice['status_label'])}.",
            styles,
            width,
        )
    reference = []
    if invoice["quotation_number"]:
        reference.append(f"Penawaran {esc(invoice['quotation_number'])}")
    if invoice["term"]:
        portion = (
            f" ({fmt.percent(invoice['term']['percent'])}%)" if invoice["term"]["percent"] else ""
        )
        reference.append(f"{esc(invoice['term']['name'])}{portion}")
    project = snapshot["project"]
    story.append(
        label_value_table(
            (
                (
                    "Ditagihkan kepada",
                    client_markup(snapshot["client"], with_tax_id=True),
                    "Proyek",
                    f"{esc(project['number'])} · {esc(project['name'])}",
                ),
                (
                    "Perihal",
                    f"<b>{esc(invoice['title'])}</b>",
                    "Referensi",
                    " · ".join(reference) or "-",
                ),
            ),
            styles,
            width,
        )
    )
    story.append(Spacer(1, 4 * mm))

    headers = ["No", "Uraian", "Volume", "Satuan", "Harga satuan", "Jumlah"]
    widths = [9 * mm, 0.0, 18 * mm, 16 * mm, 28 * mm, 30 * mm]
    widths[1] = width - sum(widths)
    rows: list[list[Any]] = [
        [
            Paragraph(h, styles.th_right if i in {2, 4, 5} else styles.th)
            for i, h in enumerate(headers)
        ]
    ]
    for line in snapshot["lines"]:
        rows.append(
            [
                str(line["no"]),
                Paragraph(esc(line["description"]), styles.cell),
                Paragraph(fmt.quantity(line["quantity"]), styles.cell_right),
                Paragraph(esc(line["unit"]), styles.cell),
                Paragraph(fmt.unit_price(line["unit_price"], currency), styles.cell_right),
                Paragraph(fmt.money(line["amount"], currency), styles.cell_right),
            ]
        )
    story.append(grid_table(rows, widths, accent))
    story.append(Spacer(1, 3 * mm))

    lines: list[tuple[str, str]] = [("Subtotal", fmt.money(totals["subtotal"], currency))]
    if totals["tax_label"]:
        lines.append(
            (
                f"{totals['tax_label']} {fmt.percent(totals['tax_rate_percent'])}%",
                fmt.money(totals["tax_amount"], currency),
            )
        )
    block: list[Flowable] = [
        amounts_table(
            lines,
            ("Total tagihan", fmt.money(totals["grand_total"], currency)),
            styles,
            width,
            accent,
        )
    ]
    if totals["amount_in_words"]:
        block += [
            Spacer(1, 2 * mm),
            Paragraph(f"<i>Terbilang: {esc(totals['amount_in_words'])}</i>", styles.right),
        ]
    story.append(KeepTogether(block))

    pay = snapshot["payment_info"]
    if pay["bank_name"] and pay["account_number"]:
        holder = f" a.n. {esc(pay['account_holder'])}" if pay["account_holder"] else ""
        story.append(Spacer(1, 4 * mm))
        story.append(
            Table(
                [
                    [
                        Paragraph(
                            "<b>Pembayaran</b><br/>"
                            f"Transfer ke {esc(pay['bank_name'])}, nomor rekening "
                            f"<b>{esc(pay['account_number'])}</b>{holder}. "
                            f"Cantumkan nomor invoice {esc(number or '')} pada berita transfer.",
                            styles.body,
                        )
                    ]
                ],
                colWidths=[width],
                style=TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.5, accent),
                        ("BACKGROUND", (0, 0), (-1, -1), tint(accent, 0.06)),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                ),
            )
        )
    story += text_sections((("Catatan", invoice["notes"]),), styles)
    story.append(
        KeepTogether(
            signature_block(
                (
                    ("Disusun oleh", invoice["prepared_by"], invoice["submitted_at"]),
                    ("Disetujui oleh", invoice["approved_by"], invoice["approved_at"]),
                ),
                approval_notes(invoice, document),
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
        subject=invoice["title"],
        furniture=page_furniture(
            pagesize=pagesize,
            running_title=title,
            footer_left=footer_left(number, verification_code, preview),
            footer_text=settings["footer_text"],
            preview=preview,
        ),
    )
