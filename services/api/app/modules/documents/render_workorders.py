"""SPK and BAST PDFs from their snapshots (layout shared with the other documents).

Same rules as every document: values come from the snapshot only, user text is escaped, no
signature or stamp is drawn, and the template adds no legal clauses or handover conditions —
terms, item conditions and notes appear only as the users wrote them.
"""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, LongTable, Paragraph, Spacer

from app.modules.documents import formatting as fmt
from app.modules.documents.pdf_common import (
    Styles,
    amounts_table,
    build_pdf,
    content_width,
    esc,
    footer_left,
    label_value_table,
    letterhead,
    page_furniture,
    party_signature_block,
    preview_banner,
    text_sections,
)
from app.modules.documents.render_billing import client_markup, grid_table, terms_table

# Wider label columns than the default: "Pemberi kerja" / "Jangka waktu" stay on one line.
PARTY_COLUMNS = (0.15, 0.36, 0.14, 0.35)


def _company_name(company: dict[str, Any]) -> str:
    return str(company["legal_name"] or company["name"])


def _internal_notes(record: dict[str, Any], document: dict[str, Any]) -> list[str]:
    notes = []
    if record["approved_at"]:
        notes.append(
            f"Disetujui secara internal oleh {record['approved_by'] or '—'} di RABmate AI pada "
            f"{fmt.tanggal_waktu(record['approved_at'])}."
        )
    if not document["preview"]:
        notes.append(
            f"Diterbitkan oleh {document['issued_by']} pada "
            f"{fmt.tanggal_waktu(document['issued_at'])}."
        )
    return notes


def _header_right(document: dict[str, Any], date_line: str) -> list[str]:
    number = document["number"]
    return [
        esc(document["title"].upper()),
        "<font color='#B42318'><b>PRATINJAU</b></font>"
        if document["preview"]
        else f"<b>{esc(number)}</b>",
        date_line,
    ]


def _period(spk: dict[str, Any]) -> str:
    start, end = spk["start_date"], spk["end_date"]
    if start and end:
        return f"{fmt.tanggal(start)} s.d. {fmt.tanggal(end)}"
    if start:
        return f"Mulai {fmt.tanggal(start)}"
    if end:
        return f"Selesai {fmt.tanggal(end)}"
    return "—"


def _finish(
    story: list[Flowable], snapshot: dict[str, Any], subject: str, verification_code: str | None
) -> bytes:
    document = snapshot["document"]
    preview = bool(document["preview"])
    title = f"{document['number'] or 'PRATINJAU'} — {document['title']}"
    return build_pdf(
        story,
        pagesize=A4,
        title=title,
        author=_company_name(snapshot["company"]),
        subject=subject,
        furniture=page_furniture(
            pagesize=A4,
            running_title=title,
            footer_left=footer_left(document["number"], verification_code, preview),
            footer_text=snapshot["settings"]["footer_text"],
            preview=preview,
        ),
    )


# --------------------------------------------------------------------------- SPK


def render_spk_pdf(snapshot: dict[str, Any], verification_code: str | None = None) -> bytes:
    document = snapshot["document"]
    settings = snapshot["settings"]
    spk = snapshot["spk"]
    contract = snapshot["contract"]
    currency = snapshot["currency"]
    preview = bool(document["preview"])
    accent = colors.HexColor(settings["accent_color"])
    styles = Styles(accent)
    width = content_width(A4)
    company = snapshot["company"]

    date_line = (
        f"Tanggal {esc(fmt.tanggal(spk['issue_date']))}"
        if spk["issue_date"]
        else "Belum diterbitkan"
    )
    story: list[Flowable] = letterhead(
        company, settings, _header_right(document, date_line), styles, width, accent
    )
    if preview:
        story += preview_banner(
            "PRATINJAU — SPK belum diterbitkan dan belum bernomor. Status: "
            f"{esc(spk['status_label'])}.",
            styles,
            width,
        )
    project = snapshot["project"]
    story.append(
        label_value_table(
            (
                (
                    "Pemberi kerja",
                    client_markup(snapshot["client"]),
                    "Pelaksana",
                    f"<b>{esc(_company_name(company))}</b>",
                ),
                (
                    "Proyek",
                    f"{esc(project['number'])} — {esc(project['name'])}",
                    "Referensi",
                    f"Penawaran {esc(spk['quotation_number'])}<br/>"
                    f"{esc(spk['rab_number'])} versi {spk['rab_version_no']}",
                ),
                (
                    "Lokasi",
                    esc(spk["location"] or "—"),
                    "Jangka waktu",
                    esc(_period(spk)),
                ),
            ),
            styles,
            width,
            PARTY_COLUMNS,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<b>Perihal: {esc(spk['title'])}</b>", styles.body))
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "Surat perintah kerja ini merujuk pada penawaran "
            f"{esc(spk['quotation_number'])} ({esc(spk['quotation_subject'])}) yang telah "
            "diterima oleh pemberi kerja, dengan rincian sebagai berikut.",
            styles.body,
        )
    )
    story += text_sections((("Lingkup pekerjaan", spk["scope"]),), styles)

    if snapshot["items"]:
        story.append(Paragraph("Rincian volume pekerjaan", styles.heading))
        story.append(_spk_items_table(snapshot["items"], styles, width, accent, settings))

    story.append(Paragraph("Nilai kontrak", styles.heading))
    lines: list[tuple[str, str]] = [
        ("Nilai sebelum pajak", fmt.money(contract["taxable_base"], currency))
    ]
    if contract["tax_label"]:
        lines.append(
            (
                f"{contract['tax_label']} {fmt.percent(contract['tax_rate_percent'])}%",
                fmt.money(contract["tax_amount"], currency),
            )
        )
    block: list[Flowable] = [
        amounts_table(
            lines,
            ("Nilai kontrak", fmt.money(contract["contract_value"], currency)),
            styles,
            width,
            accent,
        )
    ]
    if contract["amount_in_words"]:
        block += [
            Spacer(1, 2 * mm),
            Paragraph(f"<i>Terbilang: {esc(contract['amount_in_words'])}</i>", styles.right),
        ]
    story.append(KeepTogether(block))
    if snapshot["payment_terms"]:
        story.append(Paragraph("Jadwal pembayaran", styles.heading))
        story.append(terms_table(snapshot["payment_terms"], currency, styles, width, accent))
    story += text_sections((("Ketentuan", spk["terms"]), ("Catatan", spk["notes"])), styles)
    story.append(
        KeepTogether(
            party_signature_block(
                (
                    (
                        "Pemberi kerja",
                        snapshot["client"]["name"] if snapshot["client"] else None,
                        spk["client_signatory"]["name"],
                        spk["client_signatory"]["title"],
                    ),
                    (
                        "Pelaksana",
                        _company_name(company),
                        spk["company_signatory"]["name"],
                        spk["company_signatory"]["title"],
                    ),
                ),
                _internal_notes(spk, document),
                styles,
                width,
            )
        )
    )
    return _finish(story, snapshot, spk["title"], verification_code)


def _spk_items_table(
    items: list[dict[str, Any]],
    styles: Styles,
    width: float,
    accent: colors.Color,
    settings: dict[str, Any],
) -> LongTable:
    show_codes = bool(settings["show_item_codes"]) and any(i["code"] for i in items)
    headers = [
        "No",
        *(["Kode"] if show_codes else []),
        "Uraian pekerjaan / barang",
        "Volume",
        "Satuan",
    ]
    widths = [9 * mm, *([20 * mm] if show_codes else []), 0.0, 24 * mm, 18 * mm]
    desc = 2 if show_codes else 1
    widths[desc] = width - sum(widths)
    rows: list[list[Any]] = [
        [Paragraph(h, styles.th_right if h == "Volume" else styles.th) for h in headers]
    ]
    for item in items:
        text = f"<b>{esc(item['name'])}</b>"
        if item["specification"]:
            text += f"<br/><font size='7'>{esc(item['specification'])}</font>"
        row: list[Any] = [str(item["no"])]
        if show_codes:
            row.append(Paragraph(esc(item["code"] or ""), styles.cell))
        row += [
            Paragraph(text, styles.cell),
            Paragraph(fmt.quantity(item["quantity"]), styles.cell_right),
            Paragraph(esc(item["unit"]), styles.cell),
        ]
        rows.append(row)
    return grid_table(rows, widths, accent)


# --------------------------------------------------------------------------- BAST


def render_bast_pdf(snapshot: dict[str, Any], verification_code: str | None = None) -> bytes:
    document = snapshot["document"]
    settings = snapshot["settings"]
    bast = snapshot["bast"]
    preview = bool(document["preview"])
    accent = colors.HexColor(settings["accent_color"])
    styles = Styles(accent)
    width = content_width(A4)
    company = snapshot["company"]

    date_line = (
        f"Tanggal serah terima {esc(fmt.tanggal(bast['handover_date']))}"
        if bast["handover_date"]
        else "Tanggal serah terima —"
    )
    story: list[Flowable] = letterhead(
        company, settings, _header_right(document, date_line), styles, width, accent
    )
    if preview:
        story += preview_banner(
            "PRATINJAU — BAST belum diterbitkan dan belum bernomor. Status: "
            f"{esc(bast['status_label'])}.",
            styles,
            width,
        )
    project = snapshot["project"]
    story.append(
        label_value_table(
            (
                (
                    "Pemberi kerja",
                    client_markup(snapshot["client"]),
                    "Pelaksana",
                    f"<b>{esc(_company_name(company))}</b>",
                ),
                (
                    "Proyek",
                    f"{esc(project['number'])} — {esc(project['name'])}",
                    "Referensi",
                    f"SPK {esc(bast['spk_number'])}<br/>Penawaran {esc(bast['quotation_number'])}",
                ),
                (
                    "Jenis",
                    f"<b>{esc(bast['kind_label'])}</b>",
                    "Lokasi",
                    esc(bast["location"] or "—"),
                ),
            ),
            styles,
            width,
            PARTY_COLUMNS,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<b>Perihal: {esc(bast['title'])}</b>", styles.body))
    story.append(Spacer(1, 2 * mm))
    when = fmt.tanggal(bast["handover_date"]) if bast["handover_date"] else "—"
    story.append(
        Paragraph(
            f"Berita acara ini mencatat serah terima pada tanggal {esc(when)} atas pekerjaan "
            f"dan/atau barang berikut berdasarkan SPK {esc(bast['spk_number'])}.",
            styles.body,
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(_bast_lines_table(snapshot["lines"], styles, width, accent))
    if any(line["contract"] for line in snapshot["lines"]):
        story.append(Spacer(1, 1.5 * mm))
        story.append(
            Paragraph(
                'Volume kontrak sesuai SPK. "Sebelumnya" = volume pada BAST terbit sebelumnya; '
                '"Kumulatif" = sebelumnya + BAST ini. Baris tanpa volume kontrak adalah '
                "pekerjaan/barang di luar rincian kontrak.",
                styles.small,
            )
        )
    story += text_sections((("Ketentuan", bast["terms"]), ("Catatan", bast["notes"])), styles)
    story.append(
        KeepTogether(
            party_signature_block(
                (
                    (
                        "Yang menyerahkan",
                        _company_name(company),
                        bast["delivered_by"]["name"],
                        bast["delivered_by"]["title"],
                    ),
                    (
                        "Yang menerima",
                        snapshot["client"]["name"] if snapshot["client"] else None,
                        bast["received_by"]["name"],
                        bast["received_by"]["title"],
                    ),
                ),
                _internal_notes(bast, document),
                styles,
                width,
            )
        )
    )
    return _finish(story, snapshot, bast["title"], verification_code)


def _bast_lines_table(
    lines: list[dict[str, Any]], styles: Styles, width: float, accent: colors.Color
) -> LongTable:
    headers = [
        "No",
        "Uraian",
        "Satuan",
        "Vol. kontrak",
        "Sebelumnya",
        "BAST ini",
        "Kumulatif",
        "Kondisi / catatan",
    ]
    # Wide enough that no header word breaks mid-word (measured at the 7.5 pt bold header font).
    widths = [9 * mm, 0.0, 15 * mm, 16 * mm, 23 * mm, 17 * mm, 19 * mm, 28 * mm]
    widths[1] = width - sum(widths)
    numeric = {3, 4, 5, 6}
    rows: list[list[Any]] = [
        [
            Paragraph(h, styles.th_right if i in numeric else styles.th)
            for i, h in enumerate(headers)
        ]
    ]
    for line in lines:
        ref = line["contract"]
        description = esc(line["description"])
        if ref:
            description += f"<br/><font size='7'>Item kontrak no. {ref['no']}</font>"
        rows.append(
            [
                str(line["no"]),
                Paragraph(description, styles.cell),
                Paragraph(esc(line["unit"]), styles.cell),
                Paragraph(
                    fmt.quantity(ref["contract_quantity"]) if ref else "—", styles.cell_right
                ),
                Paragraph(fmt.quantity(ref["delivered_before"]) if ref else "—", styles.cell_right),
                Paragraph(f"<b>{fmt.quantity(line['quantity'])}</b>", styles.cell_right),
                Paragraph(fmt.quantity(ref["cumulative"]) if ref else "—", styles.cell_right),
                Paragraph(esc(line["condition"] or "—"), styles.cell),
            ]
        )
    return grid_table(rows, widths, accent)
