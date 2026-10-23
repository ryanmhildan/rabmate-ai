"""Source documents: upload a quotation/price list to a project, list, read back (ADR-043)."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorResponse
from app.core.ratelimit import EXPENSIVE
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.intake import service
from app.modules.intake.models import SourceDocument
from app.modules.intake.ocr import OcrEngine, get_ocr
from app.modules.intake.schemas import PageText, SourceDocumentOut, SourceTextOut, UploadOut

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 413, 422)
}
P = Permission

router = APIRouter(tags=["source-documents"], responses=ERRORS)


def get_ocr_engine(settings: Settings = Depends(get_settings)) -> OcrEngine:
    """Dependency (overridden in tests): the OCR engine for scanned pages and images."""
    return get_ocr(settings)


class UploadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


def _disposition(filename: str) -> str:
    """attachment with an ASCII fallback plus the exact (UTF-8) name, per RFC 6266/5987."""
    fallback = "".join(ch if ch.isascii() and ch not in '"\\' else "_" for ch in filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.post(
    "/projects/{project_id}/source-documents",
    dependencies=EXPENSIVE,
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Unggah dokumen sumber (PDF, XLSX, CSV, PNG/JPEG) ke proyek",
)
def upload(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(require(P.AI_USE, P.RAB_WRITE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UploadOut:
    limit = settings.upload_max_mb * 1024 * 1024
    content = file.file.read(limit + 1)  # bounded read; never loads more than the limit
    if len(content) > limit:
        raise UploadTooLargeError(f"Ukuran file melebihi {settings.upload_max_mb} MB.")
    doc, created = service.upload(db, ctx, project_id, file.filename, content, settings)
    return UploadOut(**SourceDocumentOut.model_validate(doc).model_dump(), duplicate=not created)


@router.get(
    "/projects/{project_id}/source-documents",
    response_model=list[SourceDocumentOut],
    summary="Dokumen sumber proyek (terbaru dulu)",
)
def list_documents(
    project_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> list[SourceDocument]:
    return service.list_for_project(db, ctx, project_id)


@router.get(
    "/source-documents/{document_id}",
    response_model=SourceDocumentOut,
    summary="Detail dokumen sumber",
)
def get_document(
    document_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> SourceDocument:
    return service.get(db, ctx, document_id)


@router.get(
    "/source-documents/{document_id}/text",
    response_model=SourceTextOut,
    summary="Teks yang terbaca dari dokumen (setelah diproses asisten AI)",
)
def get_text(
    document_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> SourceTextOut:
    extraction = service.cached_extraction(db, ctx, document_id)
    if extraction is None:
        return SourceTextOut(read=False)
    return SourceTextOut(
        read=True,
        pages=[PageText.model_validate(p) for p in extraction.get("pages", [])],
        warnings=list(extraction.get("warnings", [])),
    )


@router.get(
    "/source-documents/{document_id}/file",
    summary="Unduh file asli (selalu sebagai lampiran)",
    response_class=Response,
)
def download(
    document_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> Response:
    doc = service.get(db, ctx, document_id, with_content=True)
    # Uploaded files are untrusted: always a download, never rendered by the browser from our
    # origin (nosniff is set globally).
    return Response(
        doc.content,
        media_type=doc.content_type,
        headers={"Content-Disposition": _disposition(doc.filename), "Cache-Control": "no-store"},
    )
