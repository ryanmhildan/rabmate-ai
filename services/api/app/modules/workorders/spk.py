"""SPK (work orders) from accepted quotations: drafting, review, issuance and voiding (ADR-038)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RequestContext
from app.core.errors import (
    BusinessValidationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    VersionConflictError,
)
from app.core.pagination import PageParams, apply_sort, escape_like, paginate
from app.modules.billing import common
from app.modules.billing import quotations as quotation_service
from app.modules.billing.models import ClientResponse, DocStatus, Quotation
from app.modules.billing.workflow import DELETABLE, Action
from app.modules.documents import service as documents
from app.modules.documents.models import DocumentType, FileFormat, IssuedDocument
from app.modules.documents.render_workorders import render_spk_pdf
from app.modules.documents.service import (
    CONTENT_TYPES,
    AlreadyIssuedError,
    IdempotencyKeyReusedError,
    RenderedFile,
    safe_filename,
)
from app.modules.documents.snapshot import Issuance, SnapshotIntegrityError, snapshot_sha256
from app.modules.identity.permissions import Permission
from app.modules.numbering.service import format_number, next_value
from app.modules.rab.models import RabVersion
from app.modules.workorders.models import Bast, Spk
from app.modules.workorders.schemas import SpkCreate, SpkUpdate
from app.modules.workorders.snapshots import build_spk_snapshot

ENTITY = "spk"
WRITE = Permission.PROJECTS_WRITE
SORT = {
    "created_at": Spk.created_at,
    "number": Spk.number,
    "issue_date": Spk.issue_date,
    "contract_value": Spk.contract_value,
}
EDIT_FIELDS = (
    "title",
    "start_date",
    "end_date",
    "location",
    "scope",
    "terms",
    "notes",
    "client_signatory_name",
    "client_signatory_title",
    "company_signatory_name",
    "company_signatory_title",
)


# --------------------------------------------------------------------------- loading


def get(db: Session, ctx: RequestContext, spk_id: uuid.UUID, *, lock: bool = False) -> Spk:
    stmt = (
        select(Spk)
        .where(Spk.id == spk_id, Spk.organization_id == ctx.organization_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=Spk)
    spk = db.execute(stmt).unique().scalar_one_or_none()
    if spk is None:
        raise NotFoundError("SPK tidak ditemukan.")
    return spk


def active_for_quotation(db: Session, ctx: RequestContext, quotation_id: uuid.UUID) -> Spk | None:
    return (
        db.execute(
            select(Spk).where(
                Spk.organization_id == ctx.organization_id,
                Spk.quotation_id == quotation_id,
                Spk.status != DocStatus.VOID,
            )
        )
        .unique()
        .scalar_one_or_none()
    )


def active_basts(db: Session, spk: Spk) -> list[Bast]:
    return list(
        db.execute(
            select(Bast).where(
                Bast.spk_id == spk.id,
                Bast.organization_id == spk.organization_id,
                Bast.status != DocStatus.VOID,
            )
        )
        .unique()
        .scalars()
    )


def bast_counts(db: Session, ctx: RequestContext, spk_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not spk_ids:
        return {}
    stmt = (
        select(Bast.spk_id, func.count())
        .where(
            Bast.organization_id == ctx.organization_id,
            Bast.spk_id.in_(spk_ids),
            Bast.status != DocStatus.VOID,
        )
        .group_by(Bast.spk_id)
    )
    return {key: count for key, count in db.execute(stmt)}


def list_spk(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    status: DocStatus | None,
    project_id: uuid.UUID | None,
    quotation_id: uuid.UUID | None,
    sort: str | None,
) -> tuple[list[Spk], int]:
    stmt = select(Spk).where(Spk.organization_id == ctx.organization_id)
    if q:
        term = f"%{escape_like(q)}%"
        stmt = stmt.where(or_(Spk.number.ilike(term), Spk.title.ilike(term)))
    if status:
        stmt = stmt.where(Spk.status == status)
    if project_id:
        stmt = stmt.where(Spk.project_id == project_id)
    if quotation_id:
        stmt = stmt.where(Spk.quotation_id == quotation_id)
    return paginate(db, apply_sort(stmt, sort, SORT, default="-created_at"), params)


def _require_contract_source(quotation: Quotation) -> None:
    if quotation.status is not DocStatus.ISSUED or (
        quotation.client_response is not ClientResponse.ACCEPTED
    ):
        raise ConflictError(
            "SPK hanya dapat dibuat dari penawaran terbit yang sudah diterima klien.",
            details={
                "quotation_status": quotation.status.value,
                "client_response": quotation.client_response.value
                if quotation.client_response
                else None,
            },
        )


# --------------------------------------------------------------------------- authoring


def create(db: Session, ctx: RequestContext, payload: SpkCreate) -> Spk:
    # Locks the quotation: two concurrent requests cannot both create its SPK.
    quotation = quotation_service.get(db, ctx, payload.quotation_id, lock=True)
    _require_contract_source(quotation)
    existing = active_for_quotation(db, ctx, quotation.id)
    if existing is not None:
        raise ConflictError(
            "Penawaran ini sudah memiliki SPK.",
            details={"spk_id": str(existing.id), "number": existing.number},
        )
    project = quotation.project
    if project.client_id is None:
        raise BusinessValidationError("Proyek belum memiliki klien.")
    settings = documents.settings_row(db, ctx)
    start, end = project.start_date, project.end_date
    spk = Spk(
        organization_id=ctx.organization_id,
        status=DocStatus.DRAFT,
        project_id=project.id,
        client_id=project.client_id,
        quotation_id=quotation.id,
        title=(payload.title or project.name)[:300],
        start_date=start,
        end_date=end if start is None or end is None or end >= start else None,
        location=project.location,
        scope=quotation.scope,
        terms=settings.spk_terms if settings else None,
        currency=quotation.currency,
        contract_value=quotation.grand_total,
        created_by_id=ctx.user_id,
    )
    db.add(spk)
    db.flush()
    common.record_audit(
        db,
        ctx,
        "spk.create",
        ENTITY,
        spk.id,
        f"SPK dari {quotation.number}",
        {"contract_value": {"from": None, "to": spk.contract_value}},
    )
    db.commit()
    return get(db, ctx, spk.id)


def _require_draft(spk: Spk, version: int | None = None) -> None:
    if spk.status is not DocStatus.DRAFT:
        raise ConflictError("SPK hanya dapat diubah saat berstatus draft.")
    if version is not None and version != spk.version:
        raise VersionConflictError(details={"current_version": spk.version})


def update(db: Session, ctx: RequestContext, spk_id: uuid.UUID, payload: SpkUpdate) -> Spk:
    spk = get(db, ctx, spk_id, lock=True)
    _require_draft(spk, payload.version)
    if payload.start_date and payload.end_date and payload.end_date < payload.start_date:
        raise BusinessValidationError(
            "Tanggal selesai tidak boleh sebelum tanggal mulai.",
            details=[{"loc": ["body", "end_date"], "msg": "Sebelum tanggal mulai."}],
        )
    before = {f: getattr(spk, f) for f in EDIT_FIELDS}
    for field in EDIT_FIELDS:
        setattr(spk, field, getattr(payload, field))
    changes = {
        f: {"from": before[f], "to": getattr(spk, f)}
        for f in EDIT_FIELDS
        if before[f] != getattr(spk, f)
    }
    if changes:
        db.flush()
        common.record_audit(db, ctx, "spk.update", ENTITY, spk.id, spk.title, changes)
    db.commit()
    return get(db, ctx, spk_id)


def missing_for_submit(spk: Spk) -> list[dict[str, Any]]:
    """What must be filled in before review (the parties and the work must be stated)."""
    required = {
        "start_date": "Tanggal mulai wajib diisi.",
        "scope": "Lingkup pekerjaan wajib diisi.",
        "client_signatory_name": "Nama penanda tangan pemberi kerja wajib diisi.",
        "company_signatory_name": "Nama penanda tangan pelaksana wajib diisi.",
    }
    return [
        {"loc": ["body", field], "msg": msg}
        for field, msg in required.items()
        if not getattr(spk, field)
    ]


def transition(
    db: Session, ctx: RequestContext, spk_id: uuid.UUID, action: Action, note: str | None
) -> Spk:
    spk = get(db, ctx, spk_id, lock=True)
    if action is Action.SUBMIT:
        missing = missing_for_submit(spk)
        if missing:
            raise BusinessValidationError("Lengkapi SPK sebelum diajukan.", details=missing)
        _require_contract_source(spk.quotation)
    before = common.apply_transition(db, ctx, spk, ENTITY, action, note, write=WRITE)
    db.flush()
    common.record_audit(
        db,
        ctx,
        f"spk.{action.value}",
        ENTITY,
        spk.id,
        spk.number or spk.title,
        {"status": {"from": before.value, "to": spk.status.value}},
    )
    db.commit()
    return get(db, ctx, spk_id)


def delete(db: Session, ctx: RequestContext, spk_id: uuid.UUID) -> None:
    spk = get(db, ctx, spk_id, lock=True)
    if spk.status not in DELETABLE:
        raise ConflictError("Hanya SPK draft atau ditolak yang dapat dihapus.")
    common.record_audit(db, ctx, "spk.delete", ENTITY, spk.id, spk.title)
    db.delete(spk)
    db.commit()


# --------------------------------------------------------------------------- documents


def _snapshot(
    db: Session, ctx: RequestContext, spk: Spk, issuance: Issuance | None
) -> dict[str, Any]:
    quotation = spk.quotation
    version = db.execute(
        select(RabVersion)
        .where(
            RabVersion.id == quotation.rab_version_id,
            RabVersion.organization_id == ctx.organization_id,
        )
        .options(selectinload(RabVersion.items))
    ).scalar_one()
    try:
        return build_spk_snapshot(
            organization=ctx.organization,
            settings_row=documents.settings_row(db, ctx),
            spk=spk,
            quotation=quotation,
            rab=version.rab,
            version=version,
            approvals=common.approvals_of(db, ctx, ENTITY, spk.id),
            issuance=issuance,
            generated_at=issuance.issued_at if issuance else common.now(),
        )
    except SnapshotIntegrityError as exc:
        raise ConflictError(str(exc)) from None


def preview_pdf(db: Session, ctx: RequestContext, spk_id: uuid.UUID) -> RenderedFile:
    spk = get(db, ctx, spk_id)
    content = render_spk_pdf(_snapshot(db, ctx, spk, None))
    name = safe_filename(f"PRATINJAU_{spk.number or 'SPK'}_{spk.title}")
    return RenderedFile(f"{name}.pdf", CONTENT_TYPES[FileFormat.PDF], content)


@dataclass(frozen=True)
class Issued:
    spk: Spk
    document: IssuedDocument
    created: bool


def issue(
    db: Session, ctx: RequestContext, spk_id: uuid.UUID, idempotency_key: str | None
) -> Issued:
    spk = get(db, ctx, spk_id, lock=True)
    if idempotency_key and (existing := documents.find_by_key(db, ctx, idempotency_key)):
        if existing.spk_id != spk.id:
            raise IdempotencyKeyReusedError(details={"document_id": str(existing.id)})
        return Issued(spk, existing, False)
    if spk.status is DocStatus.ISSUED:
        raise AlreadyIssuedError("SPK ini sudah diterbitkan.")
    if spk.status is not DocStatus.APPROVED:
        raise ConflictError(
            "Hanya SPK yang sudah disetujui yang dapat diterbitkan.",
            details={"status": spk.status.value},
        )
    _require_contract_source(spk.quotation)
    issue_date = common.today()
    year = issue_date.year
    spk.number = format_number("SPK", year, next_value(db, ctx.organization_id, "spk", year))
    spk.issue_date = issue_date
    spk.status = DocStatus.ISSUED
    issued_at = common.now()
    snapshot = _snapshot(db, ctx, spk, Issuance(spk.number, issued_at, ctx.user.full_name))
    digest = snapshot_sha256(snapshot)
    try:
        document = documents.store_document(
            db,
            ctx,
            doc_type=DocumentType.SPK,
            number=spk.number,
            title=spk.title,
            project_id=spk.project_id,
            currency=spk.currency,
            total_amount=spk.contract_value,
            snapshot=snapshot,
            digest=digest,
            files={FileFormat.PDF: render_spk_pdf(snapshot, digest)},
            idempotency_key=idempotency_key,
            issued_at=issued_at,
            sources={"spk_id": spk.id},
            summary=f"{spk.number} — {spk.title}",
        )
    except IntegrityError:
        db.rollback()
        existing = documents.find_by_key(db, ctx, idempotency_key) if idempotency_key else None
        if existing is not None and existing.spk_id == spk_id:
            return Issued(get(db, ctx, spk_id), existing, False)
        raise
    db.commit()
    return Issued(get(db, ctx, spk_id), documents.get_document(db, ctx, document.id), True)


def void(db: Session, ctx: RequestContext, spk_id: uuid.UUID, reason: str) -> Spk:
    if not ctx.can(Permission.DOCUMENTS_ISSUE):
        raise PermissionDeniedError()
    spk = get(db, ctx, spk_id, lock=True)
    if spk.status is not DocStatus.ISSUED:
        raise ConflictError("Hanya SPK terbit yang dapat dibatalkan; draft cukup dihapus.")
    if active_basts(db, spk):
        raise ConflictError("Batalkan atau hapus dulu BAST yang dibuat dari SPK ini.")
    spk.status = DocStatus.VOID
    spk.voided_at = common.now()
    spk.voided_by_id = ctx.user_id
    spk.void_reason = reason
    documents.void_active(db, ctx, reason, spk_id=spk.id)
    db.flush()
    common.record_audit(
        db,
        ctx,
        "spk.void",
        ENTITY,
        spk.id,
        spk.number or spk.title,
        {"status": {"from": "issued", "to": "void"}, "void_reason": {"from": None, "to": reason}},
    )
    db.commit()
    return get(db, ctx, spk_id)
