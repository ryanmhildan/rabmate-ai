"""What an uploaded file really is, decided from its bytes — never from its name alone."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

from app.modules.intake.models import SourceKind

# Decompressed size an XLSX may expand to (zip-bomb guard); real spreadsheets stay far below.
MAX_XLSX_UNPACKED = 100 * 1024 * 1024
EXTENSIONS = {
    SourceKind.PDF: (".pdf",),
    SourceKind.XLSX: (".xlsx",),
    SourceKind.CSV: (".csv", ".txt"),
    SourceKind.IMAGE: (".png", ".jpg", ".jpeg"),
}
ACCEPTED = ", ".join(ext for exts in EXTENSIONS.values() for ext in exts)


class UnsupportedFileError(ValueError):
    pass


@dataclass(frozen=True)
class Sniffed:
    kind: SourceKind
    content_type: str


def safe_filename(name: str | None) -> str:
    """A display name only (never used as a path): last path segment, no control characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip(" .")
    return (base or "dokumen")[:255]


def _xlsx_ok(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            unpacked = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        return False
    if unpacked > MAX_XLSX_UNPACKED:
        raise UnsupportedFileError("Isi XLSX terlalu besar setelah diekstrak.")
    return "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names)


def _looks_like_text(content: bytes) -> bool:
    sample = content[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            sample.decode("cp1252")
        except UnicodeDecodeError:
            return False
    return True


def sniff(filename: str, content: bytes) -> Sniffed:
    if not content:
        raise UnsupportedFileError("File kosong.")
    lower = filename.lower()
    if content.startswith(b"%PDF-"):
        kind, content_type = SourceKind.PDF, "application/pdf"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        kind, content_type = SourceKind.IMAGE, "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        kind, content_type = SourceKind.IMAGE, "image/jpeg"
    elif content.startswith(b"PK\x03\x04") and _xlsx_ok(content):
        kind = SourceKind.XLSX
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif lower.endswith(EXTENSIONS[SourceKind.CSV]) and _looks_like_text(content):
        kind, content_type = SourceKind.CSV, "text/csv"
    else:
        raise UnsupportedFileError(f"Format tidak didukung. Unggah {ACCEPTED}.")
    if not lower.endswith(EXTENSIONS[kind]):
        raise UnsupportedFileError(
            f"Isi file adalah {kind.value.upper()}, tetapi ekstensinya tidak cocok."
        )
    return Sniffed(kind, content_type)
