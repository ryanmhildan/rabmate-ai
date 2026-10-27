"""Checks and re-encodes an uploaded letterhead (kop surat) image.

The upload is untrusted: its type is decided from the bytes, its pixel count is checked before
decoding (decompression-bomb guard), and what gets stored is a fresh PNG drawn by the server,
without the upload's metadata (EXIF, GPS, embedded profiles or comments). Only PNG and JPEG are
accepted; ReportLab embeds the stored PNG as is.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 25_000_000
MIN_WIDTH = 600
# Wider sources are scaled down: 2400 px across a 180 mm print width is about 340 dpi.
MAX_STORED_WIDTH = 2400

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


class LetterheadImageError(ValueError):
    """The upload cannot be used as a letterhead; the message is shown to the user."""


@dataclass(frozen=True)
class NormalizedImage:
    png: bytes
    width: int
    height: int
    sha256: str


def normalize(content: bytes) -> NormalizedImage:
    if not content:
        raise LetterheadImageError("File kosong.")
    if not (content.startswith(PNG_MAGIC) or content.startswith(JPEG_MAGIC)):
        raise LetterheadImageError("Format tidak didukung. Unggah gambar PNG atau JPEG.")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            if probe.width * probe.height > MAX_PIXELS:
                raise LetterheadImageError(
                    "Resolusi gambar terlalu besar (maksimal 25 megapiksel)."
                )
            probe.verify()
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            # Phone photos store their rotation in EXIF; apply it before EXIF is dropped.
            image = ImageOps.exif_transpose(source)
    except LetterheadImageError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise LetterheadImageError("Gambar rusak atau tidak dapat dibaca.") from None

    if image.width < MIN_WIDTH:
        raise LetterheadImageError(
            f"Lebar gambar minimal {MIN_WIDTH} piksel agar kop tetap tajam saat dicetak."
        )
    if image.height >= image.width:
        raise LetterheadImageError(
            "Kop surat harus melebar (lebar lebih besar dari tinggi). Potong gambar hanya pada "
            "bagian kopnya."
        )

    has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    image = image.convert("RGBA" if has_alpha else "RGB")
    # Many editors save an alpha channel with no transparent pixel; dropping it keeps the PDF
    # free of a soft mask that changes nothing.
    if has_alpha and image.getchannel("A").getextrema() == (255, 255):
        image = image.convert("RGB")
    if image.width > MAX_STORED_WIDTH:
        height = max(1, round(image.height * MAX_STORED_WIDTH / image.width))
        image = image.resize((MAX_STORED_WIDTH, height), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    # A new image object carries no info dict from the source, so nothing but pixels is written.
    clean = Image.new(image.mode, image.size)
    clean.paste(image)
    clean.save(buffer, format="PNG", optimize=True)
    png = buffer.getvalue()
    return NormalizedImage(png, clean.width, clean.height, hashlib.sha256(png).hexdigest())
