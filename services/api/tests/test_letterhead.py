"""Letterhead (kop surat): upload checks, re-encoding, PDFs of every type, snapshots, access."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents import letterhead
from app.modules.documents.pdf_common import LetterheadMismatchError
from app.modules.documents.render_billing import render_invoice_pdf, render_quotation_pdf
from app.modules.documents.render_pdf import render_rab_pdf
from app.modules.documents.render_workorders import render_bast_pdf, render_spk_pdf
from app.modules.identity.permissions import Role
from tests.document_samples import (
    bast_snapshot,
    invoice_snapshot,
    many_items,
    quotation_snapshot,
    sample_snapshot,
    spk_snapshot,
)
from tests.factories import LoginAs, Tenant, make_user
from tests.test_billing_api import Roles, client_id, issued_quotation, rab, roles  # noqa: F401
from tests.test_rab_api import Rab, ok

URL = "/api/v1/document-settings/letterhead"


def png(width: int = 1200, height: int = 300, mode: str = "RGB", **save: Any) -> bytes:
    image = Image.new(mode, (width, height), "white")
    if mode in ("RGB", "RGBA"):
        image.paste((31, 78, 121), (0, 0, width, height // 4))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", **save)
    return buffer.getvalue()


def jpeg(width: int = 1600, height: int = 400) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def images_per_page(content: bytes) -> list[int]:
    return [len(page.images) for page in PdfReader(io.BytesIO(content)).pages]


def page_text(content: bytes, index: int = 0) -> str:
    return " ".join(PdfReader(io.BytesIO(content)).pages[index].extract_text().split())


def page_lines(content: bytes, index: int = 0) -> list[str]:
    return PdfReader(io.BytesIO(content)).pages[index].extract_text().splitlines()


def upload(browser: TestClient, content: bytes, name: str = "kop.png") -> Any:
    return browser.put(URL, files={"file": (name, content, "application/octet-stream")})


# --------------------------------------------------------------------------- image checks


def test_normalize_reencodes_png_without_metadata() -> None:
    info = PngInfo()
    info.add_text("Author", "rahasia-internal")
    result = letterhead.normalize(png(save={"pnginfo": info}))
    assert result.png.startswith(letterhead.PNG_MAGIC)
    assert (result.width, result.height) == (1200, 300)
    assert result.sha256 == hashlib.sha256(result.png).hexdigest()
    assert b"rahasia-internal" not in result.png
    with Image.open(io.BytesIO(result.png)) as stored:
        assert "Author" not in stored.info


def test_normalize_accepts_jpeg_keeps_transparency_and_scales_wide_images() -> None:
    assert letterhead.normalize(jpeg()).png.startswith(letterhead.PNG_MAGIC)
    see_through = Image.new("RGBA", (1200, 300), (0, 0, 0, 0))
    see_through.paste((31, 78, 121, 255), (0, 0, 1200, 75))
    buffer = io.BytesIO()
    see_through.save(buffer, format="PNG")
    with Image.open(io.BytesIO(letterhead.normalize(buffer.getvalue()).png)) as kept:
        assert kept.mode == "RGBA"
    # An alpha channel without a single transparent pixel is dropped.
    with Image.open(io.BytesIO(letterhead.normalize(png(mode="RGBA")).png)) as opaque:
        assert opaque.mode == "RGB"
    wide = letterhead.normalize(png(4800, 600))
    assert (wide.width, wide.height) == (2400, 300)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "File kosong"),
        (b"GIF89a" + b"\x00" * 20, "PNG atau JPEG"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "PNG atau JPEG"),
        (letterhead.PNG_MAGIC + b"bukan gambar", "rusak"),
        (png(400, 100), "minimal 600 piksel"),
        (png(800, 800), "melebar"),
        (png(800, 1200), "melebar"),
        # 6000 x 5000 = 30 megapixels in a few KB: refused before decoding the pixels.
        (png(6000, 5000, mode="1"), "megapiksel"),
    ],
    ids=["empty", "gif", "svg", "corrupt", "narrow", "square", "portrait", "pixel-bomb"],
)
def test_normalize_refuses_unusable_images(content: bytes, message: str) -> None:
    with pytest.raises(letterhead.LetterheadImageError, match=message):
        letterhead.normalize(content)


# --------------------------------------------------------------------------- PDF renderers

RENDERERS: list[tuple[str, Callable[..., bytes], Callable[..., dict[str, Any]]]] = [
    ("rab", render_rab_pdf, sample_snapshot),
    ("quotation", render_quotation_pdf, quotation_snapshot),
    ("invoice", render_invoice_pdf, invoice_snapshot),
    ("spk", render_spk_pdf, spk_snapshot),
    ("bast", render_bast_pdf, bast_snapshot),
]


def with_letterhead(build: Callable[..., dict[str, Any]], image: letterhead.NormalizedImage) -> Any:
    meta = {"sha256": image.sha256, "width_px": image.width, "height_px": image.height}
    return build(settings={"letterhead": meta})


@pytest.mark.parametrize(("name", "render", "build"), RENDERERS)
def test_every_pdf_prints_the_letterhead_image_on_page_one(
    name: str, render: Callable[..., bytes], build: Callable[..., dict[str, Any]]
) -> None:
    image = letterhead.normalize(png())
    plain = render(build(), "a" * 64)
    assert images_per_page(plain)[0] == 0

    snapshot = with_letterhead(build, image)
    content = render(snapshot, "a" * 64, image.png)
    assert images_per_page(content)[0] == 1
    assert content == render(snapshot, "a" * 64, image.png), "rendering must stay deterministic"

    with pytest.raises(LetterheadMismatchError):
        render(snapshot, "a" * 64, None)
    with pytest.raises(LetterheadMismatchError):
        render(snapshot, "a" * 64, letterhead.normalize(jpeg()).png)
    # Snapshots without a letterhead (all documents issued before this feature) ignore bytes.
    assert images_per_page(render(build(), "a" * 64, image.png))[0] == 0


def test_letterhead_replaces_the_text_block_and_stays_on_page_one() -> None:
    image = letterhead.normalize(png())
    plain = render_rab_pdf(sample_snapshot(), "a" * 64)
    plain_text = page_text(plain)
    assert "Jl. Merdeka No. 1" in plain_text
    assert "Solusi jaringan & listrik" in plain_text  # the tagline belongs to the text block
    assert not any("Tanggal terbit" in line and "versi" in line for line in page_lines(plain))

    # Under a kop the title block is centred and compact: the date and version share one line.
    single = render_rab_pdf(with_letterhead(sample_snapshot, image), "a" * 64, image.png)
    assert any("Tanggal terbit" in line and "versi" in line for line in page_lines(single))

    snapshot = sample_snapshot(**many_items(80))
    snapshot["settings"]["letterhead"] = with_letterhead(sample_snapshot, image)["settings"][
        "letterhead"
    ]
    content = render_rab_pdf(snapshot, "a" * 64, image.png)
    first = page_text(content)
    assert "Jl. Merdeka No. 1" not in first
    assert "Solusi jaringan" not in first
    assert "RENCANA ANGGARAN BIAYA" in first
    counts = images_per_page(content)
    assert len(counts) > 1
    assert counts[0] == 1
    assert set(counts[1:]) == {0}


def test_tall_letterhead_is_scaled_to_the_height_limit() -> None:
    image = letterhead.normalize(png(1000, 900))
    content = render_rab_pdf(with_letterhead(sample_snapshot, image), "a" * 64, image.png)
    assert images_per_page(content)[0] == 1
    assert "RENCANA ANGGARAN BIAYA" in page_text(content)


# --------------------------------------------------------------------------- API


def test_upload_replace_delete_and_issued_documents_keep_their_image(
    db_session: Session,
    tenant: Tenant,
    roles: Roles,  # noqa: F811
    rab: Rab,  # noqa: F811
) -> None:
    browser = tenant.browser
    assert ok(browser.get(URL)) is None
    assert browser.get(f"{URL}/image").status_code == 404

    first = ok(upload(browser, png(), "Kop PT Alfa.png"))
    assert first["filename"] == "Kop PT Alfa.png"
    assert first["content_type"] == "image/png"
    assert (first["width_px"], first["height_px"]) == (1200, 300)
    assert first["uploaded_by"]["full_name"] == tenant.owner.full_name
    image = browser.get(f"{URL}/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "no-store"
    assert hashlib.sha256(image.content).hexdigest() == first["sha256"]

    # The template's own version is untouched, so unsaved template edits are never discarded.
    assert ok(browser.get("/api/v1/document-settings"))["version"] == 0

    quotation = issued_quotation(roles, rab)
    document = ok(browser.get(f"/api/v1/documents?quotation_id={quotation['id']}"))["items"][0]
    detail = ok(browser.get(f"/api/v1/documents/{document['id']}"))
    assert detail["snapshot"]["settings"]["letterhead"] == {
        "sha256": first["sha256"],
        "width_px": 1200,
        "height_px": 300,
    }
    stored = browser.get(f"/api/v1/documents/{document['id']}/files/pdf")
    assert images_per_page(stored.content)[0] == 1

    preview = browser.get(f"/api/v1/quotations/{quotation['id']}/preview.pdf")
    assert images_per_page(preview.content)[0] == 1

    second = ok(upload(browser, jpeg(), "kop-baru.jpg"))
    assert second["sha256"] != first["sha256"]
    assert second["content_type"] == "image/png"
    again = browser.get(f"/api/v1/documents/{document['id']}/files/pdf")
    assert again.content == stored.content, "an issued document never changes"

    assert browser.delete(URL).status_code == 204
    assert ok(browser.get(URL)) is None
    assert browser.delete(URL).status_code == 404
    after = browser.get(f"/api/v1/quotations/{quotation['id']}/preview.pdf")
    assert images_per_page(after.content)[0] == 0
    assert browser.get(f"/api/v1/documents/{document['id']}/files/pdf").content == stored.content

    actions = (
        db_session.execute(
            select(AuditLog.action)
            .where(
                AuditLog.organization_id == tenant.org.id,
                AuditLog.entity_type == "document_letterhead",
            )
            .order_by(AuditLog.created_at)
        )
        .scalars()
        .all()
    )
    assert actions == [
        "document_settings.letterhead_upload",
        "document_settings.letterhead_replace",
        "document_settings.letterhead_delete",
    ]


def test_rab_preview_and_issue_use_the_letterhead(
    tenant: Tenant,
    rab: Rab,  # noqa: F811
) -> None:
    saved = ok(upload(tenant.browser, png()))
    preview = tenant.browser.get(rab.url(1, "/preview.pdf"))
    assert images_per_page(preview.content)[0] == 1
    ok(rab.act("submit"))
    ok(rab.act("approve", note="OK"))
    document = ok(
        tenant.browser.post(rab.url(1, "/documents"), headers={"Idempotency-Key": "kop-rab-01"}),
        201,
    )
    detail = ok(tenant.browser.get(f"/api/v1/documents/{document['id']}"))
    assert detail["snapshot"]["settings"]["letterhead"]["sha256"] == saved["sha256"]
    pdf = tenant.browser.get(f"/api/v1/documents/{document['id']}/files/pdf").content
    assert images_per_page(pdf)[0] == 1


def test_upload_limits(tenant: Tenant) -> None:
    too_big = upload(tenant.browser, b"\x89PNG\r\n\x1a\n" + b"\x00" * letterhead.MAX_UPLOAD_BYTES)
    assert too_big.status_code == 413
    assert "2 MB" in too_big.json()["error"]["message"]
    not_image = upload(tenant.browser, b"%PDF-1.7 kop", "kop.pdf")
    assert not_image.status_code == 422
    assert "PNG atau JPEG" in not_image.json()["error"]["message"]
    portrait = upload(tenant.browser, png(800, 1200))
    assert portrait.status_code == 422
    assert ok(tenant.browser.get(URL)) is None


def test_letterhead_access_and_isolation(
    db_session: Session, tenant: Tenant, other_tenant: Tenant, login_as: LoginAs
) -> None:
    manager = login_as(make_user(db_session, tenant.org, Role.PROJECT_MANAGER))
    viewer = login_as(make_user(db_session, tenant.org, Role.VIEWER))
    assert upload(manager, png()).status_code == 403
    ok(upload(tenant.browser, png()))
    assert manager.delete(URL).status_code == 403
    assert ok(viewer.get(URL))["width_px"] == 1200
    assert viewer.get(f"{URL}/image").status_code == 200

    assert ok(other_tenant.browser.get(URL)) is None
    assert other_tenant.browser.get(f"{URL}/image").status_code == 404
    assert other_tenant.browser.delete(URL).status_code == 404
    assert ok(tenant.browser.get(URL)) is not None
