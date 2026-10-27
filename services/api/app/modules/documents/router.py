from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import AppError, ErrorResponse, NotFoundError
from app.core.pagination import Page, PageParams, page_params
from app.core.ratelimit import EXPENSIVE
from app.db.session import get_db
from app.modules.documents import letterhead, schemas, service
from app.modules.documents.models import (
    DocumentLetterhead,
    DocumentSettings,
    DocumentStatus,
    DocumentType,
    FileFormat,
    IssuedDocument,
)
from app.modules.identity.permissions import Permission

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}

documents_router = APIRouter(prefix="/documents", tags=["documents"], responses=ERRORS)
settings_router = APIRouter(prefix="/document-settings", tags=["documents"], responses=ERRORS)
rab_documents_router = APIRouter(prefix="/rab", tags=["documents"], responses=ERRORS)

# Generated files hold business data: never cache them in shared or browser caches.
NO_STORE = {"Cache-Control": "no-store"}

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9_\-:.]+$",
        description="Kunci unik per permintaan penerbitan; retry dengan kunci sama → dokumen sama.",
    ),
]


def _disposition(kind: str, filename: str) -> str:
    # Filenames are produced by service.safe_filename (ASCII only), so no RFC 5987 encoding needed.
    return f'{kind}; filename="{filename}"'


def file_response(rendered: service.RenderedFile, *, inline: bool) -> Response:
    return Response(
        rendered.content,
        media_type=rendered.content_type,
        headers={
            "Content-Disposition": _disposition(
                "inline" if inline else "attachment", rendered.filename
            ),
            **NO_STORE,
        },
    )


def _out(document: IssuedDocument) -> schemas.DocumentOut:
    return schemas.DocumentOut.model_validate(document)


# --------------------------------------------------------------------------- settings


def _settings_out(row: DocumentSettings | None) -> schemas.DocumentSettingsOut:
    if row is None:
        return schemas.DocumentSettingsOut(version=0, updated_at=None)
    return schemas.DocumentSettingsOut.model_validate(row, from_attributes=True)


@settings_router.get("", response_model=schemas.DocumentSettingsOut, summary="Template dokumen")
def get_settings(
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_READ)),
    db: Session = Depends(get_db),
) -> schemas.DocumentSettingsOut:
    return _settings_out(service.settings_row(db, ctx))


@settings_router.put("", response_model=schemas.DocumentSettingsOut, summary="Ubah template")
def put_settings(
    payload: schemas.DocumentSettingsUpdate,
    ctx: RequestContext = Depends(require(Permission.ORG_UPDATE)),
    db: Session = Depends(get_db),
) -> schemas.DocumentSettingsOut:
    return _settings_out(service.update_settings(db, ctx, payload))


class LetterheadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


@settings_router.get(
    "/letterhead",
    response_model=schemas.LetterheadOut | None,
    summary="Kop surat organisasi (null bila belum diunggah)",
)
def get_letterhead(
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_READ)),
    db: Session = Depends(get_db),
) -> DocumentLetterhead | None:
    return service.letterhead_row(db, ctx)


@settings_router.get(
    "/letterhead/image",
    summary="Gambar kop surat (PNG hasil olahan server)",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def get_letterhead_image(
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_READ)),
    db: Session = Depends(get_db),
) -> Response:
    row = service.letterhead_row(db, ctx, with_content=True)
    if row is None:
        raise NotFoundError("Belum ada kop surat yang diunggah.")
    # The bytes are the server's own PNG re-encoding (no upload passes through), so showing them
    # inline in the settings page is safe; nosniff is set globally.
    return Response(
        row.content,
        media_type=row.content_type,
        headers={"Content-Disposition": 'inline; filename="kop-surat.png"', **NO_STORE},
    )


@settings_router.put(
    "/letterhead",
    dependencies=EXPENSIVE,
    response_model=schemas.LetterheadOut,
    summary="Unggah atau ganti kop surat (PNG/JPEG, maks. 2 MB)",
    responses={413: {"model": ErrorResponse}},
)
def put_letterhead(
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(require(Permission.ORG_UPDATE)),
    db: Session = Depends(get_db),
) -> DocumentLetterhead:
    limit = letterhead.MAX_UPLOAD_BYTES
    content = file.file.read(limit + 1)  # bounded read; never loads more than the limit
    if len(content) > limit:
        raise LetterheadTooLargeError("Ukuran file kop surat melebihi 2 MB.")
    return service.upload_letterhead(db, ctx, file.filename, content)


@settings_router.delete(
    "/letterhead", status_code=status.HTTP_204_NO_CONTENT, summary="Hapus kop surat"
)
def delete_letterhead(
    ctx: RequestContext = Depends(require(Permission.ORG_UPDATE)),
    db: Session = Depends(get_db),
) -> Response:
    service.delete_letterhead(db, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- RAB preview/issue


@rab_documents_router.get(
    "/{rab_id}/versions/{version_no}/preview.pdf",
    dependencies=EXPENSIVE,
    summary="Pratinjau PDF (data terkini, bertanda PRATINJAU, tidak disimpan)",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def preview_pdf(
    rab_id: uuid.UUID,
    version_no: int,
    download: bool = Query(False),
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> Response:
    return file_response(service.preview_pdf(db, ctx, rab_id, version_no), inline=not download)


@rab_documents_router.get(
    "/{rab_id}/versions/{version_no}/export.xlsx",
    dependencies=EXPENSIVE,
    summary="Ekspor XLSX (data terkini versi ini)",
    response_class=Response,
)
def export_xlsx(
    rab_id: uuid.UUID,
    version_no: int,
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> Response:
    return file_response(service.export_xlsx(db, ctx, rab_id, version_no), inline=False)


@rab_documents_router.post(
    "/{rab_id}/versions/{version_no}/documents",
    dependencies=EXPENSIVE,
    response_model=schemas.DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Terbitkan dokumen RAB (snapshot + PDF + XLSX); idempoten dengan Idempotency-Key",
    responses={200: {"description": "Retry dengan Idempotency-Key yang sama: dokumen yang sama"}},
)
def issue(
    rab_id: uuid.UUID,
    version_no: int,
    response: Response,
    idempotency_key: IdempotencyKey = None,
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> schemas.DocumentOut:
    document, created = service.issue_rab(db, ctx, rab_id, version_no, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return _out(document)


# --------------------------------------------------------------------------- documents


@documents_router.get("", response_model=Page[schemas.DocumentOut], summary="Dokumen terbit")
def list_documents(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100),
    doc_type: DocumentType | None = Query(None),
    status_: DocumentStatus | None = Query(None, alias="status"),
    rab_id: uuid.UUID | None = Query(None),
    rab_version_id: uuid.UUID | None = Query(None),
    quotation_id: uuid.UUID | None = Query(None),
    invoice_id: uuid.UUID | None = Query(None),
    spk_id: uuid.UUID | None = Query(None),
    bast_id: uuid.UUID | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    sort: str | None = Query(None, description="issued_at, number; awali '-'"),
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.DocumentOut]:
    items, total = service.list_documents(
        db,
        ctx,
        params,
        q=q,
        doc_type=doc_type,
        status=status_,
        rab_id=rab_id,
        rab_version_id=rab_version_id,
        quotation_id=quotation_id,
        invoice_id=invoice_id,
        spk_id=spk_id,
        bast_id=bast_id,
        project_id=project_id,
        sort=sort,
    )
    return Page(
        items=[_out(d) for d in items], total=total, page=params.page, page_size=params.page_size
    )


@documents_router.get(
    "/{document_id}", response_model=schemas.DocumentDetail, summary="Dokumen + snapshot"
)
def get_document(
    document_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_READ)),
    db: Session = Depends(get_db),
) -> schemas.DocumentDetail:
    document = service.get_document(db, ctx, document_id, with_snapshot=True)
    return schemas.DocumentDetail.model_validate(document)


@documents_router.get(
    "/{document_id}/files/{file_format}",
    summary="Unduh berkas tersimpan (byte yang sama dengan saat diterbitkan)",
    response_class=Response,
)
def download_file(
    document_id: uuid.UUID,
    file_format: FileFormat,
    download: bool = Query(False),
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_READ)),
    db: Session = Depends(get_db),
) -> Response:
    stored = service.get_file(db, ctx, document_id, file_format)
    inline = file_format is FileFormat.PDF and not download
    return Response(
        stored.content,
        media_type=stored.content_type,
        headers={
            "Content-Disposition": _disposition(
                "inline" if inline else "attachment", stored.filename
            ),
            "ETag": f'"{stored.sha256}"',
            **NO_STORE,
        },
    )


@documents_router.post(
    "/{document_id}/void", response_model=schemas.DocumentOut, summary="Batalkan dokumen terbit"
)
def void(
    document_id: uuid.UUID,
    payload: schemas.VoidIn,
    ctx: RequestContext = Depends(require(Permission.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> schemas.DocumentOut:
    return _out(service.void_document(db, ctx, document_id, payload.reason))
