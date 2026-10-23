"""Routes for importing RAB items from CSV/XLSX into a draft version."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import ErrorResponse
from app.core.ratelimit import EXPENSIVE
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.pricing.router import PayloadTooLargeError
from app.modules.rab import item_import, item_imports
from app.modules.rab.item_imports import ImportJobOut
from app.shared.spreadsheet import MAX_BYTES

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422)
}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/rab", tags=["rab"], responses=ERRORS)


@router.get("/item-imports/template", summary="Template impor item RAB (xlsx atau csv)")
def template(
    format: Literal["xlsx", "csv"] = Query("xlsx"),
    _: RequestContext = Depends(require(Permission.RAB_READ)),
) -> Response:
    if format == "csv":
        return Response(
            item_import.template_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="template-item-rab.csv"'},
        )
    return Response(
        item_import.template_xlsx(),
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="template-item-rab.xlsx"'},
    )


@router.post(
    "/{rab_id}/versions/{version_no}/imports",
    dependencies=EXPENSIVE,
    response_model=ImportJobOut,
    status_code=status.HTTP_201_CREATED,
    summary="Unggah CSV/XLSX item → pratinjau (belum disimpan); hanya versi draft",
)
def upload(
    rab_id: uuid.UUID,
    version_no: int,
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> ImportJobOut:
    content = file.file.read(MAX_BYTES + 1)  # bounded read; never loads more than the limit
    if len(content) > MAX_BYTES:
        raise PayloadTooLargeError()
    job = item_imports.preview(
        db, ctx, rab_id, version_no, item_imports.safe_filename(file.filename), content
    )
    return item_imports.to_out(job)


@router.get(
    "/{rab_id}/versions/{version_no}/imports/{job_id}",
    response_model=ImportJobOut,
    summary="Pratinjau impor item",
)
def get_import(
    rab_id: uuid.UUID,
    version_no: int,
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> ImportJobOut:
    _, job = item_imports.get_job(db, ctx, rab_id, version_no, job_id)
    return item_imports.to_out(job)


@router.post(
    "/{rab_id}/versions/{version_no}/imports/{job_id}/commit",
    response_model=ImportJobOut,
    summary="Tambahkan baris valid sebagai item (idempoten)",
)
def commit(
    rab_id: uuid.UUID,
    version_no: int,
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> ImportJobOut:
    return item_imports.to_out(item_imports.commit(db, ctx, rab_id, version_no, job_id))


@router.post(
    "/{rab_id}/versions/{version_no}/imports/{job_id}/discard",
    response_model=ImportJobOut,
    summary="Batalkan impor item",
)
def discard(
    rab_id: uuid.UUID,
    version_no: int,
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> ImportJobOut:
    return item_imports.to_out(item_imports.discard(db, ctx, rab_id, version_no, job_id))
