"""OCR for scanned pages and images: Tesseract when installed, otherwise honestly unavailable.

Tesseract is run as a fixed command on a temporary image file — no shell, no arguments taken
from documents or the AI, a timeout per page — and its text is treated like any other document
text (untrusted data, checked by the extraction rules). Nothing is sent anywhere.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)

WINDOWS_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


@dataclass(frozen=True)
class OcrStatus:
    available: bool
    message: str
    engine: str | None = None
    languages: tuple[str, ...] = field(default=())


class OcrError(RuntimeError):
    pass


class OcrEngine(Protocol):
    def status(self) -> OcrStatus: ...

    def image_to_text(self, png: bytes) -> str: ...


class NoOcr:
    def __init__(self, message: str) -> None:
        self._message = message

    def status(self) -> OcrStatus:
        return OcrStatus(False, self._message)

    def image_to_text(self, png: bytes) -> str:
        raise OcrError(self._message)


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(  # noqa: S603 - fixed executable, list args, no shell
        command, capture_output=True, timeout=timeout, check=False, creationflags=flags
    )


class TesseractOcr:
    def __init__(self, executable: str, wanted: tuple[str, ...], timeout: float) -> None:
        self._exe = executable
        self._wanted = wanted
        self._timeout = timeout
        self._status: OcrStatus | None = None
        self._lock = threading.Lock()

    def status(self) -> OcrStatus:
        with self._lock:
            if self._status is None:
                self._status = self._probe()
            return self._status

    def _probe(self) -> OcrStatus:
        try:
            version = _run([self._exe, "--version"], 15)
            langs = _run([self._exe, "--list-langs"], 15)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.info("tesseract probe failed: %s", type(exc).__name__)
            return OcrStatus(False, "Tesseract tidak dapat dijalankan.")
        if version.returncode != 0:
            return OcrStatus(False, "Tesseract tidak dapat dijalankan.")
        first = (version.stdout or version.stderr).decode("utf-8", "replace").splitlines()
        engine = first[0].strip() if first else "tesseract"
        installed = {
            line.strip()
            for line in langs.stdout.decode("utf-8", "replace").splitlines()[1:]
            if line.strip()
        }
        usable = tuple(lang for lang in self._wanted if lang in installed)
        if not usable:
            return OcrStatus(
                False,
                f"Tesseract terpasang, tetapi bahasa {'+'.join(self._wanted)} belum tersedia.",
                engine,
            )
        missing = [lang for lang in self._wanted if lang not in installed]
        note = f" (bahasa {', '.join(missing)} belum terpasang)" if missing else ""
        return OcrStatus(True, f"{engine}, bahasa {'+'.join(usable)}{note}.", engine, usable)

    def image_to_text(self, png: bytes) -> str:
        status = self.status()
        if not status.available:
            raise OcrError(status.message)
        handle, path = tempfile.mkstemp(suffix=".png", prefix="rabmate-ocr-")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(png)
            result = _run(
                [self._exe, path, "stdout", "-l", "+".join(status.languages), "--psm", "6"],
                self._timeout,
            )
        except subprocess.TimeoutExpired:
            raise OcrError(f"OCR melewati batas {int(self._timeout)} detik per halaman.") from None
        except OSError as exc:
            raise OcrError(f"OCR gagal dijalankan ({type(exc).__name__}).") from None
        finally:
            Path(path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise OcrError("Tesseract gagal membaca gambar.")
        return result.stdout.decode("utf-8", "replace")


_engines: dict[tuple[str | None, str, int, bool], OcrEngine] = {}
_engines_lock = threading.Lock()


def get_ocr(settings: Settings) -> OcrEngine:
    """The OCR engine for these settings (probed once per process)."""
    key = (
        settings.tesseract_cmd,
        settings.ocr_languages,
        settings.ocr_timeout_seconds,
        settings.ocr_enabled,
    )
    with _engines_lock:
        engine = _engines.get(key)
        if engine is None:
            engine = _build(settings)
            _engines[key] = engine
        return engine


def _build(settings: Settings) -> OcrEngine:
    if not settings.ocr_enabled:
        return NoOcr("OCR dinonaktifkan (OCR_ENABLED=false).")
    candidates = [settings.tesseract_cmd, shutil.which("tesseract"), str(WINDOWS_DEFAULT)]
    executable = next((c for c in candidates if c and Path(c).is_file()), None)
    if executable is None:
        return NoOcr(
            "OCR tidak tersedia: Tesseract belum terpasang. Halaman hasil scan dan gambar tidak "
            "dapat dibaca; PDF digital, XLSX, dan CSV tetap dapat diproses."
        )
    languages = tuple(settings.ocr_languages.split("+"))
    return TesseractOcr(executable, languages, float(settings.ocr_timeout_seconds))
