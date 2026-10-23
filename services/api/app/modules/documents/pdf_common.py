"""Building blocks shared by every generated PDF (RAB, quotation, invoice).

Deterministic (ReportLab `invariant`), embedded Vera font, and one rule for all user text: it is
XML-escaped before it reaches a Paragraph, because ReportLab paragraph markup can load files
(`<img src>`) and create links. Nothing here calculates money.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import reportlab
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.modules.documents import formatting as fmt

# No timestamps or random document IDs in the output: identical snapshots → identical bytes.
rl_config.invariant = 1

FONT = "RMSans"
FONT_BOLD = "RMSans-Bold"
FONT_ITALIC = "RMSans-Italic"
_FONT_FILES = {
    FONT: "Vera.ttf",
    FONT_BOLD: "VeraBd.ttf",
    FONT_ITALIC: "VeraIt.ttf",
    "RMSans-BoldItalic": "VeraBI.ttf",
}

MARGIN = 15 * mm
GREY = colors.HexColor("#5F6B7A")
LINE = colors.HexColor("#C9D1DB")
DANGER = colors.HexColor("#B42318")

Draw = Callable[[canvas.Canvas, int, int], None]


def _register_fonts() -> None:
    # Bitstream Vera ships with ReportLab (permissive licence); embedded so text is selectable
    # and renders the same everywhere. Covers Latin-1 plus common punctuation (dashes, middle
    # dot, multiplication and comparison signs, euro).
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    font_dir = Path(reportlab.__file__).parent / "fonts"
    for name, filename in _FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    pdfmetrics.registerFontFamily(
        FONT, normal=FONT, bold=FONT_BOLD, italic=FONT_ITALIC, boldItalic="RMSans-BoldItalic"
    )


_register_fonts()


def esc(value: object) -> str:
    """User text → safe Paragraph markup (escaped, line breaks kept)."""
    return escape(str(value)).replace("\r\n", "\n").replace("\n", "<br/>")


def tint(color: colors.Color, amount: float) -> colors.Color:
    """Mix `color` with white; amount=0.1 → 10% colour."""
    return colors.Color(
        1 - (1 - color.red) * amount, 1 - (1 - color.green) * amount, 1 - (1 - color.blue) * amount
    )


def content_width(pagesize: tuple[float, float]) -> float:
    # SimpleDocTemplate's frame keeps 6pt padding on each side.
    return pagesize[0] - 2 * MARGIN - 12


class Styles:
    def __init__(self, accent: colors.Color) -> None:
        base = ParagraphStyle("base", fontName=FONT, fontSize=8.5, leading=10.5)
        self.body = base
        self.small = ParagraphStyle("small", parent=base, fontSize=7.5, leading=9, textColor=GREY)
        self.cell = ParagraphStyle("cell", parent=base, fontSize=8, leading=10)
        self.cell_right = ParagraphStyle("cell_right", parent=self.cell, alignment=TA_RIGHT)
        self.company = ParagraphStyle(
            "company", parent=base, fontName=FONT_BOLD, fontSize=13, leading=16
        )
        self.doc_title = ParagraphStyle(
            "doc_title",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=12,
            leading=15,
            textColor=accent,
            alignment=TA_RIGHT,
        )
        self.right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
        self.heading = ParagraphStyle(
            "heading", parent=base, fontName=FONT_BOLD, fontSize=9, leading=12, spaceBefore=6
        )
        self.banner = ParagraphStyle(
            "banner", parent=base, fontName=FONT_BOLD, textColor=DANGER, fontSize=8.5
        )
        self.th = ParagraphStyle(
            "th", parent=self.cell, fontName=FONT_BOLD, fontSize=7.5, textColor=colors.white
        )
        self.th_right = ParagraphStyle("th_r", parent=self.th, alignment=TA_RIGHT)


def _numbered_canvas(draw: Draw) -> type[canvas.Canvas]:
    """Canvas that knows the total page count when drawing headers/footers ("Halaman 1 dari 3")."""

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:
            self._pages.append(dict(self.__dict__))
            # Start a fresh page without emitting the current one yet (classic ReportLab recipe
            # for "page X of Y"); _startPage is not in the type stubs.
            self._startPage()  # type: ignore[attr-defined]

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                draw(self, self.getPageNumber(), total)
                super().showPage()
            super().save()

    return NumberedCanvas


def page_furniture(
    *,
    pagesize: tuple[float, float],
    running_title: str,
    footer_left: str,
    footer_text: str | None,
    preview: bool,
) -> Draw:
    """Watermark (preview), running title from page 2, footer line, "Halaman X dari Y"."""

    def draw(c: canvas.Canvas, page: int, total: int) -> None:
        c.saveState()
        page_width, page_height = pagesize
        if preview:
            c.setFillColor(colors.Color(0.85, 0.2, 0.15, alpha=0.08))
            c.setFont(FONT_BOLD, 70)
            c.translate(page_width / 2, page_height / 2)
            c.rotate(35)
            c.drawCentredString(0, 0, "PRATINJAU")
            c.rotate(-35)
            c.translate(-page_width / 2, -page_height / 2)
        if page > 1:
            c.setFont(FONT, 7.5)
            c.setFillColor(GREY)
            c.drawString(MARGIN, page_height - 10 * mm, f"{running_title} (lanjutan)")
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(MARGIN, 12 * mm, page_width - MARGIN, 12 * mm)
        c.setFont(FONT, 7)
        c.setFillColor(GREY)
        c.drawString(MARGIN, 8 * mm, footer_left)
        c.drawRightString(page_width - MARGIN, 8 * mm, f"Halaman {page} dari {total}")
        if footer_text:
            c.drawCentredString(page_width / 2, 4.5 * mm, footer_text[:160])
        c.restoreState()

    return draw


def footer_left(number: str | None, verification_code: str | None, preview: bool) -> str:
    if preview:
        return "PRATINJAU — bukan dokumen resmi"
    return f"{number}  ·  Kode verifikasi: {(verification_code or '—')[:16]}"


def letterhead(
    company: dict[str, Any],
    settings: dict[str, Any],
    right: Sequence[str],
    styles: Styles,
    width: float,
    accent: colors.Color,
) -> list[Flowable]:
    """Company block (from the organization profile) left; document title + `right` lines.

    `right[0]` is the document title (already safe markup); the rest are safe markup lines.
    """
    left: list[Flowable] = [
        Paragraph(esc(company["legal_name"] or company["name"]), styles.company)
    ]
    if settings.get("tagline"):
        left.append(Paragraph(f"<i>{esc(settings['tagline'])}</i>", styles.small))
    address = ", ".join(x for x in (company["address"], company["city"]) if x)
    if address:
        left.append(Paragraph(esc(address), styles.small))
    contact = "  ·  ".join(x for x in (company["phone"], company["email"], company["website"]) if x)
    if contact:
        left.append(Paragraph(esc(contact), styles.small))
    if company["tax_id"]:
        left.append(Paragraph(f"NPWP {esc(company['tax_id'])}", styles.small))

    right_flow: list[Flowable] = [Paragraph(right[0], styles.doc_title)]
    right_flow += [Paragraph(line, styles.right) for line in right[1:]]
    head = Table(
        [[left, right_flow]],
        colWidths=[width * 0.58, width * 0.42],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )
    return [
        head,
        Spacer(1, 2 * mm),
        HRFlowable(width="100%", thickness=2, color=accent, spaceAfter=4 * mm),
    ]


def preview_banner(markup: str, styles: Styles, width: float) -> list[Flowable]:
    return [
        Table(
            [[Paragraph(markup, styles.banner)]],
            colWidths=[width],
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.75, DANGER),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3F2")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        ),
        Spacer(1, 3 * mm),
    ]


def label_value_table(
    rows: Sequence[tuple[str, str, str, str]],
    styles: Styles,
    width: float,
    fractions: tuple[float, float, float, float] = (0.12, 0.38, 0.1, 0.4),
) -> Table:
    """Two label/value pairs per row; values are safe markup."""

    def p(text: str) -> Paragraph:
        return Paragraph(text, styles.body)

    return Table(
        [[p(a), p(b), p(c), p(d)] for a, b, c, d in rows],
        colWidths=[width * f for f in fractions],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TEXTCOLOR", (0, 0), (0, -1), GREY),
                ("TEXTCOLOR", (2, 0), (2, -1), GREY),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]
        ),
    )


def amounts_table(
    lines: Sequence[tuple[str, str]],
    total: tuple[str, str],
    styles: Styles,
    width: float,
    accent: colors.Color,
) -> Table:
    """Right-aligned label/amount lines ending with a bold total (all plain text, escaped here)."""
    rows: list[list[Any]] = [
        [Paragraph(esc(label), styles.right), Paragraph(esc(value), styles.right)]
        for label, value in lines
    ]
    grand = ParagraphStyle(
        "grand", parent=styles.right, fontName=FONT_BOLD, fontSize=10, leading=13
    )
    rows.append([Paragraph(esc(total[0]), grand), Paragraph(esc(total[1]), grand)])
    return Table(
        rows,
        # Wide enough for a bold total in the hundreds of billions on one line.
        colWidths=[width * 0.28, width * 0.3],
        hAlign="RIGHT",
        style=TableStyle(
            [
                ("LINEABOVE", (0, -1), (-1, -1), 1, accent),
                ("BACKGROUND", (0, -1), (-1, -1), tint(accent, 0.1)),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        ),
    )


def text_sections(sections: Sequence[tuple[str, str | None]], styles: Styles) -> list[Flowable]:
    out: list[Flowable] = []
    for title, text in sections:
        if text:
            out += [Paragraph(esc(title), styles.heading), Paragraph(esc(text), styles.body)]
    return out


def signature_block(
    blocks: Sequence[tuple[str, str | None, str | None]],
    notes: Sequence[str],
    styles: Styles,
    width: float,
) -> list[Flowable]:
    """(label, name, ISO date) per column; names come from records — no signature is drawn."""

    def cell(label: str, name: str | None, when: str | None) -> list[Flowable]:
        return [
            Paragraph(esc(label), styles.small),
            Spacer(1, 16 * mm),
            Paragraph(f"<b>{esc(name or '—')}</b>", styles.body),
            Paragraph(esc(fmt.tanggal(when) if when else ""), styles.small),
        ]

    table = Table(
        [[cell(*b) for b in blocks]],
        colWidths=[width / len(blocks)] * len(blocks),
        style=TableStyle(
            [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]
        ),
    )
    out: list[Flowable] = [Spacer(1, 6 * mm), table]
    out += [Paragraph(esc(note), styles.small) for note in notes]
    return out


def party_signature_block(
    blocks: Sequence[tuple[str, str | None, str | None, str | None]],
    notes: Sequence[str],
    styles: Styles,
    width: float,
) -> list[Flowable]:
    """(role, party, person, position) per column for documents both parties sign on paper.

    Names and positions are what users typed; the space is left blank — no signature or stamp
    is ever drawn.
    """

    def cell(role: str, party: str | None, name: str | None, position: str | None) -> list[Any]:
        return [
            Paragraph(esc(role), styles.small),
            Paragraph(f"<b>{esc(party or '—')}</b>", styles.body),
            Spacer(1, 20 * mm),
            Paragraph(f"<u><b>{esc(name or '—')}</b></u>", styles.body),
            Paragraph(esc(position or ""), styles.small),
        ]

    table = Table(
        [[cell(*b) for b in blocks]],
        colWidths=[width / len(blocks)] * len(blocks),
        style=TableStyle(
            [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]
        ),
    )
    out: list[Flowable] = [Spacer(1, 6 * mm), table, Spacer(1, 3 * mm)]
    out += [Paragraph(esc(note), styles.small) for note in notes]
    return out


def build_pdf(
    story: list[Flowable],
    *,
    pagesize: tuple[float, float],
    title: str,
    author: str,
    subject: str,
    furniture: Draw,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=title,
        author=author,
        subject=subject,
        creator="RABmate AI",
    )
    doc.build(story, canvasmaker=_numbered_canvas(furniture))
    return buffer.getvalue()
