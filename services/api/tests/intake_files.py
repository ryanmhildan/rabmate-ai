"""Small generated files for the intake tests (no fixtures checked into the repository)."""

from __future__ import annotations

import io
from collections.abc import Sequence

from openpyxl import Workbook
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.modules.intake.ocr import OcrStatus

COLUMNS = (40, 70, 250, 320, 370, 450)
QUOTE_ROWS = [
    ["No", "Uraian", "Volume", "Satuan", "Harga", "Jumlah"],
    ["1", "Kabel UTP Cat6 Belden", "305", "m", "4.300", "1.311.500"],
    ["2", "Konektor RJ45", "100", "pcs", "2.500", "250.000"],
]


def table_pdf(
    pages: Sequence[Sequence[Sequence[str]]] = (QUOTE_ROWS,),
    *,
    title: str = "PENAWARAN CV SUMBER JAYA",
    encrypt: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, encrypt=encrypt)
    for rows in pages:
        pdf.drawString(40, 800, title)
        y = 770
        for row in rows:
            for x, cell in zip(COLUMNS, row, strict=False):
                pdf.drawString(x, y, cell)
            y -= 18
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def png(width: int = 60, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def scanned_pdf() -> bytes:
    """A page with only an image on it, like a scanner produces."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    image = Image.new("RGB", (300, 120), "white")
    pdf.drawImage(ImageReader(image), 40, 600, width=300, height=120)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def xlsx(rows: Sequence[Sequence[object]], *, sheets: int = 1) -> bytes:
    workbook = Workbook()
    for index in range(sheets):
        sheet = workbook.active if index == 0 else workbook.create_sheet()
        assert sheet is not None
        sheet.title = f"RAB{index + 1}"
        for row in rows:
            sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class FakeOcr:
    def __init__(self, text: str = "", *, available: bool = True) -> None:
        self.text = text
        self.available = available
        self.calls = 0

    def status(self) -> OcrStatus:
        if not self.available:
            return OcrStatus(False, "OCR tidak tersedia (uji).")
        return OcrStatus(True, "tesseract uji, bahasa ind.", "tesseract uji", ("ind",))

    def image_to_text(self, png: bytes) -> str:
        assert png.startswith(b"\x89PNG")
        self.calls += 1
        return self.text
