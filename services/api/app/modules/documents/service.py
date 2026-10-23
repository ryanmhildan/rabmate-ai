"""Document template settings, RAB preview/export, and issuance of immutable RAB documents.

Issuance (ADR-030/031):
- Only an approved RAB version can be issued; the version row is locked for the whole operation.
- Retrying with the same Idempotency-Key returns the same document; a second issue of a version
  that already has a valid document is refused (409) — at most one is valid at a time (also a
  partial unique index).
- The snapshot is frozen and both files are rendered once, inside the issuing transaction, and
  stored; downloads serve those stored bytes, never a fresh render.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, undefer

from app.api.deps import RequestContext
from app.core.errors import (
    AppError,
    BusinessValidationError,
    ConflictError,
    NotFoundError,
    VersionConflictError,
)
from app.core.pagination import PageParams, apply_sort, escape_like, paginate
from app.modules.audit import service as audit
from app.modules.documents import schemas
from app.modules.documents.models import (
    DocumentFile,
    DocumentSettings,
    DocumentStatus,
    DocumentType,
    FileFormat,
    IssuedDocument,
)
from app.modules.documents.render_pdf import render_rab_pdf
from app.modules.documents.render_xlsx import render_rab_xlsx
from app.modules.documents.snapshot import (
    SCHEMA_VERSION,
    Issuance,
    SnapshotIntegrityError,
    build_rab_snapshot,
    settings_values,
    snapshot_sha256,
)
from app.modules.rab import service as rab_service
from app.modules.rab.models import RabDocument, RabStatus, RabVersion

ENTITY = "document"
MAX_FILE_BYTES = 20 * 1024 * 1024
CONTENT_TYPES = {
    FileFormat.PDF: "application/pdf",
    FileFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
DOCUMENT_SORT = {"issued_at": IssuedDocument.issued_at, "number": IssuedDocument.number}


class AlreadyIssuedError(AppError):
    status_code = 409
    code = "already_issued"
    message = "Versi ini sudah memiliki dokumen terbit yang berlaku."


class IdempotencyKeyReusedError(AppError):
    status_code = 422
    code = "idempotency_key_reused"
    message = "Idempotency-Key ini sudah dipakai untuk permintaan lain."


@dataclass(frozen=True)
class RenderedFile:
    filename: str
    content_type: str
    content: bytes


def _now() -> datetime:
    return datetime.now(UTC)


def safe_filename(text: str) -> str:
    """Document number → file-system friendly name ("RAB-2026-0001/V2" → "RAB-2026-0001_V2")."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "dokumen"


def _audit(
    db: Session,
    ctx: RequestContext,
    action: str,
    entity_id: uuid.UUID,
    summary: str,
    changes: dict[str, object] | None = None,
    entity_type: str = ENTITY,
) -> None:
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        changes=changes,
        ip_address=ctx.ip_address,
    )


# --------------------------------------------------------------------------- settings

SETTINGS_FIELDS = (
    "tagline",
    "accent_color",
    "footer_text",
    "rab_terms",
    "show_item_codes",
    "show_price_sources",
    "show_amount_in_words",
    "payment_bank_name",
    "payment_account_number",
    "payment_account_holder",
    "spk_terms",
    "bast_terms",
)


def settings_row(db: Session, ctx: RequestContext) -> DocumentSettings | None:
    return db.execute(
        select(DocumentSettings)
        .where(DocumentSettings.organization_id == ctx.organization_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def update_settings(
    db: Session, ctx: RequestContext, payload: schemas.DocumentSettingsUpdate
) -> DocumentSettings | None:
    row = db.execute(
        select(DocumentSettings)
        .where(DocumentSettings.organization_id == ctx.organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    current = row.version if row else 0
    if payload.version != current:
        raise VersionConflictError(details={"current_version": current})
    if row is None:
        row = DocumentSettings(organization_id=ctx.organization_id)
        db.add(row)
    before = audit.snapshot(row, SETTINGS_FIELDS) if current else {}
    for field in SETTINGS_FIELDS:
        setattr(row, field, getattr(payload, field))
    row.updated_by_id = ctx.user_id
    db.flush()
    changes = audit.diff(before, audit.snapshot(row, SETTINGS_FIELDS))
    if changes:
        _audit(
            db,
            ctx,
            "document_settings.update",
            row.id,
            "Template dokumen",
            changes,
            entity_type="document_settings",
        )
    db.commit()
    return settings_row(db, ctx)


# --------------------------------------------------------------------------- RAB snapshot


@dataclass(frozen=True)
class RabContext:
    rab: RabDocument
    version: RabVersion


def _rab_context(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, version_no: int, *, lock: bool = False
) -> RabContext:
    rab = rab_service.get_rab(db, ctx, rab_id)
    version = rab_service.get_version(db, ctx, rab_id, version_no, lock=lock)
    return RabContext(rab, version)


def _snapshot(
    db: Session,
    ctx: RequestContext,
    source: RabContext,
    issuance: Issuance | None,
    generated_at: datetime,
) -> dict[str, Any]:
    try:
        return build_rab_snapshot(
            organization=ctx.organization,
            settings=settings_values(settings_row(db, ctx)),
            rab=source.rab,
            project=source.rab.project,
            version=source.version,
            approvals=rab_service.approvals_of(db, ctx, source.version),
            issuance=issuance,
            generated_at=generated_at,
        )
    except SnapshotIntegrityError as exc:
        raise ConflictError(str(exc)) from None


def preview_pdf(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, version_no: int
) -> RenderedFile:
    source = _rab_context(db, ctx, rab_id, version_no)
    snapshot = _snapshot(db, ctx, source, None, _now())
    name = safe_filename(f"PRATINJAU_{source.rab.number}_v{version_no}")
    return RenderedFile(f"{name}.pdf", CONTENT_TYPES[FileFormat.PDF], render_rab_pdf(snapshot))


def export_xlsx(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, version_no: int
) -> RenderedFile:
    source = _rab_context(db, ctx, rab_id, version_no)
    snapshot = _snapshot(db, ctx, source, None, _now())
    status = source.version.status.value
    name = safe_filename(f"{source.rab.number}_v{version_no}_{status}")
    return RenderedFile(f"{name}.xlsx", CONTENT_TYPES[FileFormat.XLSX], render_rab_xlsx(snapshot))


# --------------------------------------------------------------------------- issuance


def _by_key(db: Session, ctx: RequestContext, key: str) -> IssuedDocument | None:
    return db.execute(
        select(IssuedDocument).where(
            IssuedDocument.organization_id == ctx.organization_id,
            IssuedDocument.idempotency_key == key,
        )
    ).scalar_one_or_none()


def _replay(existing: IssuedDocument, version: RabVersion) -> IssuedDocument:
    if existing.rab_version_id != version.id:
        raise IdempotencyKeyReusedError(details={"document_id": str(existing.id)})
    return existing


def issue_rab(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    idempotency_key: str | None,
) -> tuple[IssuedDocument, bool]:
    """Returns (document, created). created=False when an idempotent retry was replayed."""
    source = _rab_context(db, ctx, rab_id, version_no, lock=True)
    version = source.version
    if idempotency_key:
        existing = _by_key(db, ctx, idempotency_key)
        if existing is not None:
            return _replay(existing, version), False
    if version.status is not RabStatus.APPROVED:
        raise ConflictError(
            "Hanya versi RAB yang sudah disetujui yang dapat diterbitkan.",
            details={"status": version.status.value},
        )
    active = db.execute(
        select(IssuedDocument).where(
            IssuedDocument.organization_id == ctx.organization_id,
            IssuedDocument.rab_version_id == version.id,
            IssuedDocument.status == DocumentStatus.ISSUED,
        )
    ).scalar_one_or_none()
    if active is not None:
        raise AlreadyIssuedError(details={"document_id": str(active.id), "number": active.number})

    previous = db.execute(
        select(func.count())
        .select_from(IssuedDocument)
        .where(IssuedDocument.rab_version_id == version.id)
    ).scalar_one()
    number = f"{source.rab.number}/V{version.version_no}"
    if previous:
        number += f"-R{previous}"
    issued_at = _now()
    snapshot = _snapshot(
        db, ctx, source, Issuance(number, issued_at, ctx.user.full_name), issued_at
    )
    digest = snapshot_sha256(snapshot)
    try:
        document = store_document(
            db,
            ctx,
            doc_type=DocumentType.RAB,
            number=number,
            title=f"{source.rab.title} (versi {version.version_no})",
            project_id=source.rab.project_id,
            currency=version.currency,
            total_amount=version.grand_total,
            snapshot=snapshot,
            digest=digest,
            files={
                FileFormat.PDF: render_rab_pdf(snapshot, digest),
                FileFormat.XLSX: render_rab_xlsx(snapshot, digest),
            },
            idempotency_key=idempotency_key,
            issued_at=issued_at,
            sources={"rab_version_id": version.id},
            summary=f"{number} — {source.rab.title}",
        )
    except IntegrityError:
        # A concurrent request with the same key won the race: replay its document.
        db.rollback()
        if idempotency_key and (existing := _by_key(db, ctx, idempotency_key)) is not None:
            return _replay(existing, _rab_context(db, ctx, rab_id, version_no).version), False
        raise
    db.commit()
    return get_document(db, ctx, document.id), True


def store_document(
    db: Session,
    ctx: RequestContext,
    *,
    doc_type: DocumentType,
    number: str,
    title: str,
    project_id: uuid.UUID | None,
    currency: str,
    total_amount: Decimal,
    snapshot: dict[str, Any],
    digest: str,
    files: dict[FileFormat, bytes],
    idempotency_key: str | None,
    issued_at: datetime,
    sources: dict[str, uuid.UUID],
    summary: str,
) -> IssuedDocument:
    """Persists an issued document, its rendered files and the audit entry (caller commits).

    Raises IntegrityError when another request already used the idempotency key or already
    issued the same source; callers replay or refuse accordingly.
    """
    for content in files.values():
        if len(content) > MAX_FILE_BYTES:
            raise BusinessValidationError("Dokumen terlalu besar untuk diterbitkan.")
    document = IssuedDocument(
        organization_id=ctx.organization_id,
        doc_type=doc_type,
        status=DocumentStatus.ISSUED,
        number=number,
        title=title[:300],
        project_id=project_id,
        currency=currency,
        total_amount=total_amount,
        schema_version=SCHEMA_VERSION,
        snapshot=snapshot,
        snapshot_sha256=digest,
        idempotency_key=idempotency_key,
        issued_at=issued_at,
        issued_by_id=ctx.user_id,
        **sources,
    )
    db.add(document)
    db.flush()
    for file_format, content in files.items():
        db.add(
            DocumentFile(
                organization_id=ctx.organization_id,
                document_id=document.id,
                format=file_format,
                content_type=CONTENT_TYPES[file_format],
                filename=f"{safe_filename(number)}.{file_format.value}",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
            )
        )
    _audit(
        db,
        ctx,
        "document.issue",
        document.id,
        summary,
        {
            "number": {"from": None, "to": number},
            "total_amount": {"from": None, "to": total_amount},
        },
    )
    return document


def find_by_key(db: Session, ctx: RequestContext, key: str) -> IssuedDocument | None:
    return _by_key(db, ctx, key)


def void_active(
    db: Session, ctx: RequestContext, reason: str, **source: uuid.UUID
) -> IssuedDocument | None:
    """Voids the valid document of a source (quotation_id=… / invoice_id=…); caller commits."""
    ((column, value),) = source.items()
    document = db.execute(
        select(IssuedDocument)
        .where(
            IssuedDocument.organization_id == ctx.organization_id,
            getattr(IssuedDocument, column) == value,
            IssuedDocument.status == DocumentStatus.ISSUED,
        )
        .with_for_update(of=IssuedDocument)
    ).scalar_one_or_none()
    if document is None:
        return None
    _mark_void(db, ctx, document, reason)
    return document


def _mark_void(db: Session, ctx: RequestContext, document: IssuedDocument, reason: str) -> None:
    document.status = DocumentStatus.VOID
    document.voided_at = _now()
    document.voided_by_id = ctx.user_id
    document.void_reason = reason
    _audit(
        db,
        ctx,
        "document.void",
        document.id,
        document.number,
        {
            "status": {"from": DocumentStatus.ISSUED.value, "to": DocumentStatus.VOID.value},
            "void_reason": {"from": None, "to": reason},
        },
    )


# --------------------------------------------------------------------------- reading


def get_document(
    db: Session, ctx: RequestContext, document_id: uuid.UUID, *, with_snapshot: bool = False
) -> IssuedDocument:
    stmt = (
        select(IssuedDocument)
        .where(
            IssuedDocument.id == document_id,
            IssuedDocument.organization_id == ctx.organization_id,
        )
        .execution_options(populate_existing=True)
    )
    if with_snapshot:
        stmt = stmt.options(undefer(IssuedDocument.snapshot))
    document = db.execute(stmt).unique().scalar_one_or_none()
    if document is None:
        raise NotFoundError("Dokumen tidak ditemukan.")
    return document


def list_documents(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    doc_type: DocumentType | None,
    status: DocumentStatus | None,
    rab_id: uuid.UUID | None,
    rab_version_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    sort: str | None,
    quotation_id: uuid.UUID | None = None,
    invoice_id: uuid.UUID | None = None,
    spk_id: uuid.UUID | None = None,
    bast_id: uuid.UUID | None = None,
) -> tuple[list[IssuedDocument], int]:
    stmt = select(IssuedDocument).where(IssuedDocument.organization_id == ctx.organization_id)
    if q:
        term = f"%{escape_like(q)}%"
        stmt = stmt.where(or_(IssuedDocument.number.ilike(term), IssuedDocument.title.ilike(term)))
    if doc_type:
        stmt = stmt.where(IssuedDocument.doc_type == doc_type)
    if status:
        stmt = stmt.where(IssuedDocument.status == status)
    if rab_version_id:
        stmt = stmt.where(IssuedDocument.rab_version_id == rab_version_id)
    if rab_id:
        stmt = stmt.where(
            IssuedDocument.rab_version_id.in_(
                select(RabVersion.id).where(
                    RabVersion.rab_id == rab_id, RabVersion.organization_id == ctx.organization_id
                )
            )
        )
    if project_id:
        stmt = stmt.where(IssuedDocument.project_id == project_id)
    if quotation_id:
        stmt = stmt.where(IssuedDocument.quotation_id == quotation_id)
    if invoice_id:
        stmt = stmt.where(IssuedDocument.invoice_id == invoice_id)
    if spk_id:
        stmt = stmt.where(IssuedDocument.spk_id == spk_id)
    if bast_id:
        stmt = stmt.where(IssuedDocument.bast_id == bast_id)
    return paginate(db, apply_sort(stmt, sort, DOCUMENT_SORT, default="-issued_at"), params)


def get_file(
    db: Session, ctx: RequestContext, document_id: uuid.UUID, file_format: FileFormat
) -> DocumentFile:
    stored = db.execute(
        select(DocumentFile)
        .where(
            DocumentFile.document_id == document_id,
            DocumentFile.organization_id == ctx.organization_id,
            DocumentFile.format == file_format,
        )
        .options(undefer(DocumentFile.content))
    ).scalar_one_or_none()
    if stored is None:
        raise NotFoundError("Berkas dokumen tidak ditemukan.")
    return stored


def void_document(
    db: Session, ctx: RequestContext, document_id: uuid.UUID, reason: str
) -> IssuedDocument:
    document = db.execute(
        select(IssuedDocument)
        .where(
            IssuedDocument.id == document_id,
            IssuedDocument.organization_id == ctx.organization_id,
        )
        .with_for_update(of=IssuedDocument)
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Dokumen tidak ditemukan.")
    if document.status is DocumentStatus.VOID:
        raise ConflictError("Dokumen sudah dibatalkan.")
    if document.doc_type is not DocumentType.RAB:
        # Quotations, invoices, SPK and BAST are voided through their own endpoint, which also
        # voids the business record (and checks nothing still depends on it).
        raise ConflictError(
            "Dokumen penawaran, invoice, SPK, dan BAST dibatalkan dari halaman dokumen sumbernya."
        )
    _mark_void(db, ctx, document, reason)
    db.commit()
    return get_document(db, ctx, document_id)
