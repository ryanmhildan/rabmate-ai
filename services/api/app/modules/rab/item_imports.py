"""RAB item import: upload → stored preview → explicit commit into a draft version. Org-scoped.

Imported items are appended (existing items are never changed); totals are recalculated by the
same calculation module as manual edits. A committed job is never applied twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.modules.pricing.imports import safe_filename, to_out
from app.modules.pricing.models import ImportJob, ImportStatus
from app.modules.pricing.schemas import ImportJobOut
from app.modules.rab import service as rab_service
from app.modules.rab.item_import import parse_file
from app.modules.rab.models import PriceSourceType, RabItem, RabItemType, RabStatus, RabVersion
from app.shared.spreadsheet import ImportFileError

KIND = "rab_items"

__all__ = [
    "KIND",
    "ImportJobOut",
    "commit",
    "discard",
    "get_job",
    "preview",
    "safe_filename",
    "to_out",
]


def _require_draft(version: RabVersion) -> None:
    if version.status is not RabStatus.DRAFT:
        raise ConflictError("Item hanya dapat diimpor ke versi berstatus draft.")


def preview(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    filename: str,
    content: bytes,
) -> ImportJob:
    version = rab_service.get_version(db, ctx, rab_id, version_no)
    _require_draft(version)
    try:
        parsed = parse_file(filename, content)
    except ImportFileError as exc:
        raise BusinessValidationError(str(exc)) from None
    rows: list[dict[str, Any]] = [
        {
            "row": r.row,
            "valid": r.valid,
            "errors": list(r.errors),
            "data": r.data,
            "action": "add_item" if r.valid else None,
        }
        for r in parsed.rows
    ]
    valid = sum(1 for r in rows if r["valid"])
    job = ImportJob(
        organization_id=ctx.organization_id,
        kind=KIND,
        rab_version_id=version.id,
        status=ImportStatus.PREVIEWED,
        filename=filename,
        file_size=len(content),
        row_count=len(rows),
        valid_count=valid,
        error_count=len(rows) - valid,
        rows=rows,
        warnings=parsed.warnings,
        created_by_id=ctx.user_id,
    )
    db.add(job)
    db.commit()
    return job


def get_job(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    job_id: uuid.UUID,
    *,
    lock: bool = False,
) -> tuple[RabVersion, ImportJob]:
    version = rab_service.get_version(db, ctx, rab_id, version_no, lock=lock)
    stmt = select(ImportJob).where(
        ImportJob.id == job_id,
        ImportJob.organization_id == ctx.organization_id,
        ImportJob.kind == KIND,
        ImportJob.rab_version_id == version.id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise NotFoundError("Data impor tidak ditemukan.")
    return version, job


def commit(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, version_no: int, job_id: uuid.UUID
) -> ImportJob:
    # Version row locked first (same order as every other item mutation), then the job.
    version, job = get_job(db, ctx, rab_id, version_no, job_id, lock=True)
    if job.status is ImportStatus.COMMITTED:
        return job  # idempotent: a retried request must not add the items twice
    if job.status is ImportStatus.DISCARDED:
        raise ConflictError("Impor ini sudah dibatalkan.")
    _require_draft(version)
    if job.valid_count == 0:
        raise BusinessValidationError("Tidak ada baris valid untuk disimpan.")

    position = max((i.position for i in version.items), default=0)
    created = 0
    for row in job.rows:
        if not row["valid"]:
            continue
        data = row["data"]
        position += 1
        price = Decimal(data["unit_price"]) if data["unit_price"] is not None else None
        source = data["price_source"]
        if price is not None and not source:
            source = f"Impor {job.filename} baris {row['row']}"
        version.items.append(
            RabItem(
                organization_id=ctx.organization_id,
                version_id=version.id,
                position=position,
                code=data["code"],
                name=data["name"],
                category=data["category"],
                item_type=RabItemType(data["item_type"]),
                specification=data["specification"],
                quantity=Decimal(data["quantity"]),
                unit=data["unit"],
                unit_price=price,
                price_source_type=PriceSourceType.IMPORT if price is not None else None,
                price_source=source,
                notes=data["notes"],
            )
        )
        created += 1
    rab_service.recalculate(version)  # overflow etc. aborts the whole import (transaction)
    job.status = ImportStatus.COMMITTED
    job.result = {"items_created": created}
    job.committed_at = datetime.now(UTC)
    job.committed_by_id = ctx.user_id
    db.flush()
    rab_service._audit_version(
        db,
        ctx,
        version,
        "rab_item.import",
        {"items": {"from": None, "to": created}},
        summary_suffix=f"{created} item dari {job.filename}",
    )
    db.commit()
    return job


def discard(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, version_no: int, job_id: uuid.UUID
) -> ImportJob:
    _, job = get_job(db, ctx, rab_id, version_no, job_id, lock=True)
    if job.status is ImportStatus.COMMITTED:
        raise ConflictError("Impor yang sudah disimpan tidak dapat dibatalkan.")
    job.status = ImportStatus.DISCARDED
    db.commit()
    return job
