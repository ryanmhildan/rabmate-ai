"""File intake without the database: type sniffing, readers (PDF, XLSX, CSV, images), OCR."""

from __future__ import annotations

import io
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.modules.intake import ocr as ocr_module
from app.modules.intake import readers, sniff
from app.modules.intake.models import SourceKind
from app.modules.intake.ocr import NoOcr, OcrError, TesseractOcr, get_ocr
from app.modules.intake.readers import normalize_lines, read_document
from app.modules.intake.sniff import UnsupportedFileError, safe_filename
from tests.intake_files import (
    QUOTE_ROWS,
    FakeOcr,
    jpeg,
    png,
    scanned_pdf,
    table_pdf,
    xlsx,
)

NO_OCR = NoOcr("OCR tidak tersedia (uji).")


def read(kind: SourceKind, content: bytes, ocr: Any = NO_OCR, **limits: int) -> dict[str, Any]:
    return read_document(
        kind,
        content,
        ocr=ocr,
        max_pages=limits.get("max_pages", 10),
        ocr_max_pages=limits.get("ocr_max_pages", 5),
    ).to_json()


# --------------------------------------------------------------------------- sniffing


@pytest.mark.parametrize(
    ("name", "content", "kind"),
    [
        ("penawaran.pdf", table_pdf(), SourceKind.PDF),
        ("Scan.PNG", png(), SourceKind.IMAGE),
        ("foto.jpeg", jpeg(), SourceKind.IMAGE),
        ("rab.xlsx", xlsx([["a", 1]]), SourceKind.XLSX),
        ("harga.csv", b"Uraian;Harga\nSemen;65.000\n", SourceKind.CSV),
        ("daftar.txt", b"Kabel | 305 | m\n", SourceKind.CSV),
    ],
)
def test_sniffing_decides_from_the_bytes(name: str, content: bytes, kind: SourceKind) -> None:
    assert sniff.sniff(name, content).kind is kind


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("kosong.pdf", b"", "File kosong"),
        ("program.pdf", b"MZ\x90\x00binary", "Format tidak didukung"),
        ("program.exe", b"MZ\x90\x00binary", "Format tidak didukung"),
        ("penawaran.xlsx", table_pdf(), "ekstensinya tidak cocok"),
        ("gambar.pdf", png(), "ekstensinya tidak cocok"),
        ("harga.csv", b"\x00\x01\x02binary", "Format tidak didukung"),
    ],
)
def test_sniffing_refuses_unsupported_or_disguised_files(
    name: str, content: bytes, message: str
) -> None:
    with pytest.raises(UnsupportedFileError, match=message):
        sniff.sniff(name, content)


def test_a_zip_that_is_not_a_workbook_or_expands_too_far_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w/>")
        archive.writestr("[Content_Types].xml", "<Types/>")
    with pytest.raises(UnsupportedFileError, match="Format tidak didukung"):
        sniff.sniff("dokumen.xlsx", buffer.getvalue())
    monkeypatch.setattr(sniff, "MAX_XLSX_UNPACKED", 1000)
    with pytest.raises(UnsupportedFileError, match="terlalu besar"):
        sniff.sniff("rab.xlsx", xlsx([["x" * 50]] * 100))


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\a\\Penawaran Mei.pdf", "Penawaran Mei.pdf"),
        ("ha\x00rga\x1b.csv", "harga.csv"),
        ("...", "dokumen"),
        (None, "dokumen"),
        ("é" * 300 + ".pdf", "é" * 255),
    ],
)
def test_filenames_are_display_names_only(raw: str | None, safe: str) -> None:
    assert safe_filename(raw) == safe


# --------------------------------------------------------------------------- PDF


def test_pdf_tables_keep_their_columns() -> None:
    result = read(SourceKind.PDF, table_pdf())
    (page,) = result["pages"]
    assert (page["label"], page["method"]) == ("Halaman 1", "teks")
    assert page["lines"] == [
        "PENAWARAN CV SUMBER JAYA",
        "No | Uraian | Volume | Satuan | Harga | Jumlah",
        "1 | Kabel UTP Cat6 Belden | 305 | m | 4.300 | 1.311.500",
        "2 | Konektor RJ45 | 100 | pcs | 2.500 | 250.000",
    ]
    assert result["warnings"] == []


def test_pdf_page_limit_is_reported() -> None:
    result = read(SourceKind.PDF, table_pdf([QUOTE_ROWS] * 3), max_pages=2)
    assert [p["label"] for p in result["pages"]] == ["Halaman 1", "Halaman 2"]
    assert result["warnings"] == ["Hanya 2 halaman pertama dari 3 yang dibaca."]


def test_scanned_pages_need_ocr_and_say_so_when_it_is_missing() -> None:
    result = read(SourceKind.PDF, scanned_pdf())
    assert result["pages"][0]["method"] == "kosong"
    assert result["warnings"] == ["Halaman 1 tampaknya hasil scan; OCR tidak tersedia, dilewati."]
    assert result["ocr"] == {"available": False, "message": "OCR tidak tersedia (uji)."}

    engine = FakeOcr("1  Semen 50 kg   12   zak")
    result = read(SourceKind.PDF, scanned_pdf(), engine)
    assert result["pages"][0] == {
        "no": 1,
        "label": "Halaman 1",
        "method": "ocr",
        "lines": ["1 | Semen 50 kg | 12 | zak"],
    }
    assert engine.calls == 1


def test_ocr_page_limit_and_failures_are_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = FakeOcr("teks")
    result = read(SourceKind.PDF, scanned_pdf(), engine, ocr_max_pages=0)
    assert result["warnings"] == ["Halaman 1 hasil scan tidak di-OCR (batas 0 halaman)."]
    assert engine.calls == 0

    def broken(png: bytes) -> str:
        raise OcrError("Tesseract gagal membaca gambar.")

    monkeypatch.setattr(engine, "image_to_text", broken)
    result = read(SourceKind.PDF, scanned_pdf(), engine)
    assert result["warnings"] == ["Halaman 1: OCR gagal (Tesseract gagal membaca gambar.)."]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (table_pdf(encrypt="rahasia"), "dikunci kata sandi"),
        (b"%PDF-1.4 rusak", "PDF tidak dapat dibaca"),
        (table_pdf()[:300], "PDF tidak dapat dibaca"),
    ],
)
def test_locked_or_broken_pdfs_are_refused_with_a_reason(content: bytes, message: str) -> None:
    with pytest.raises(UnsupportedFileError, match=message):
        read(SourceKind.PDF, content)


def test_total_text_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readers, "MAX_TOTAL_CHARS", 60)
    result = read(SourceKind.PDF, table_pdf([QUOTE_ROWS] * 3))
    assert len(result["pages"]) == 1
    assert sum(len(line) for line in result["pages"][0]["lines"]) <= 60
    assert result["warnings"] == ["Dokumen melebihi 60 karakter; sisanya tidak dibaca."]


def test_lines_are_normalized() -> None:
    assert normalize_lines("  a  b\tc \n\n x" + " " * 3 + "y\n") == ["a | b | c", "x | y"]
    assert normalize_lines("z" * 600) == ["z" * readers.MAX_LINE_CHARS]


# --------------------------------------------------------------------------- spreadsheets


def test_xlsx_cells_are_written_out_and_formulas_never_evaluated() -> None:
    content = xlsx(
        [
            ["Uraian", "Volume", "Satuan", "Harga"],
            ["Semen 50 kg", 12, "zak", 65000],
            ["Pasir", 2.5, "m3", 350000.5],
            ["Total", "=B2*D2", None, '=HYPERLINK("http://contoh.invalid","klik")'],
            [None, None, None, None],
            ["Ada", True],
        ],
        sheets=2,
    )
    result = read(SourceKind.XLSX, content)
    assert [p["label"] for p in result["pages"]] == ["Sheet RAB1", "Sheet RAB2"]
    assert result["pages"][0]["lines"] == [
        "Uraian | Volume | Satuan | Harga",
        "Semen 50 kg | 12 | zak | 65.000",
        "Pasir | 2,5 | m3 | 350.000,5",
        "Total | (rumus) |  | (rumus)",
        "Ada | ya",
    ]


def test_xlsx_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readers, "MAX_SHEETS", 1)
    monkeypatch.setattr(readers, "MAX_ROWS_PER_SHEET", 2)
    result = read(SourceKind.XLSX, xlsx([["a"], ["b"], ["c"]], sheets=2))
    assert result["pages"][0]["lines"] == ["a", "b"]
    assert result["warnings"] == [
        "Hanya 1 sheet pertama yang dibaca.",
        "Sheet 'RAB1': hanya 2 baris dibaca.",
    ]


def test_csv_keeps_values_as_written() -> None:
    content = "Uraian;Volume;Harga\nSemen;12;65.000\n=cmd|' /C calc'!A0;1;2\n".encode("cp1252")
    (page,) = read(SourceKind.CSV, content)["pages"]
    assert page["lines"] == [
        "Uraian | Volume | Harga",
        "Semen | 12 | 65.000",
        "=cmd|' /C calc'!A0 | 1 | 2",  # plain text for the extraction rules; never evaluated
    ]


# --------------------------------------------------------------------------- images & OCR


def test_images_are_read_only_with_ocr() -> None:
    result = read(SourceKind.IMAGE, png())
    assert result["pages"] == []
    assert result["warnings"] == ["Gambar hanya dapat dibaca dengan OCR. OCR tidak tersedia (uji)."]
    result = read(SourceKind.IMAGE, jpeg(), FakeOcr("Kabel  305  m"))
    assert result["pages"][0]["lines"] == ["Kabel | 305 | m"]


def test_oversized_or_broken_images_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsupportedFileError, match="Gambar tidak dapat dibaca"):
        read(SourceKind.IMAGE, png()[:40])
    monkeypatch.setattr(readers, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(UnsupportedFileError, match="terlalu besar"):
        read(SourceKind.IMAGE, png(), FakeOcr("x"))


def test_ocr_is_honestly_unavailable_without_tesseract(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.modules.intake.ocr.shutil.which", lambda _: None)
    monkeypatch.setattr(ocr_module, "WINDOWS_DEFAULT", tmp_path / "tidak-ada.exe")
    missing = get_ocr(settings.model_copy(update={"tesseract_cmd": str(tmp_path / "x.exe")}))
    assert missing.status().available is False
    assert "Tesseract belum terpasang" in missing.status().message
    with pytest.raises(OcrError):
        missing.image_to_text(png())
    disabled = get_ocr(settings.model_copy(update={"ocr_enabled": False}))
    assert disabled.status().message == "OCR dinonaktifkan (OCR_ENABLED=false)."


def _completed(stdout: str, code: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], code, stdout.encode(), b"")


def test_tesseract_runs_as_a_fixed_command_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    seen_files: list[Path] = []

    def fake_run(command: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        if command[1] == "--version":
            return _completed("tesseract 5.4.0\n")
        if command[1] == "--list-langs":
            return _completed("List of available languages (2):\neng\nosd\n")
        seen_files.append(Path(command[1]))
        assert Path(command[1]).read_bytes().startswith(b"\x89PNG")
        return _completed("Kabel  305  m\n")

    monkeypatch.setattr(ocr_module, "_run", fake_run)
    engine = TesseractOcr("tesseract.exe", ("ind", "eng"), 30)
    status = engine.status()
    assert status.available is True
    assert status.languages == ("eng",)
    assert status.message == "tesseract 5.4.0, bahasa eng (bahasa ind belum terpasang)."
    assert engine.image_to_text(png()) == "Kabel  305  m\n"
    assert calls[-1][0] == "tesseract.exe"
    assert calls[-1][2:] == ["stdout", "-l", "eng", "--psm", "6"]
    assert not seen_files[0].exists()  # the temporary image is removed

    def slow(command: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(ocr_module, "_run", slow)
    with pytest.raises(OcrError, match="batas 30 detik"):
        engine.image_to_text(png())

    no_language = TesseractOcr("tesseract.exe", ("ind",), 30)
    monkeypatch.setattr(ocr_module, "_run", fake_run)
    assert no_language.status().available is False
    assert "bahasa ind belum tersedia" in no_language.status().message
