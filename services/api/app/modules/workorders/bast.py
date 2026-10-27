"""BAST (handover records) under issued SPKs: lines, delivery rule, review, issuance (ADR-039)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.modules.billing.models import DocStatus
from app.modules.billing.workflow import DELETABLE, Action
from app.modules.documents import service as documents
from app.modules.documents.models import DocumentType, FileFormat, IssuedDocument
from app.modules.documents.render_workorders import render_bast_pdf
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
from app.modules.workorders import progress
from app.modules.workorders import spk as spk_service
from app.modules.workorders.models import Bast, BastItem, BastKind, Spk
from app.modules.workorders.schemas import BastCreate, BastItemIn, BastUpdate
from app.modules.workorders.snapshots import BAST_KIND_LABELS, build_bast_snapshot

ENTITY = "bast"
WRITE = Permission.PROJECTS_WRITE
SORT = {
    "created_at": Bast.created_at,
    "number": Bast.number,
    "handover_date": Bast.handover_date,
}
EDIT_FIELDS = (
    "title",
    "handover_date",
    "location",
    "delivered_by_name",
    "delivered_by_title",
    "received_by_name",
    "received_by_title",
    "terms",
    "notes",
)


# --------------------------------------------------------------------------- loading


def get(db: Session, ctx: RequestContext, bast_id: uuid.UUID, *, lock: bool = False) -> Bast:
    stmt = (
        select(Bast)
        .where(Bast.id == bast_id, Bast.organization_id == ctx.organization_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=Bast)
    bast = db.execute(stmt).unique().scalar_one_or_none()
    if bast is None:
        raise NotFoundError("BAST tidak ditemukan.")
    return bast


def final_of(db: Session, ctx: RequestContext, spk_id: uuid.UUID) -> Bast | None:
    return (
        db.execute(
            select(Bast).where(
                Bast.organization_id == ctx.organization_id,
                Bast.spk_id == spk_id,
                Bast.kind == BastKind.FINAL,
                Bast.status != DocStatus.VOID,
            )
        )
        .unique()
        .scalar_one_or_none()
    )


def item_counts(
    db: Session, ctx: RequestContext, bast_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not bast_ids:
        return {}
    stmt = (
        select(BastItem.bast_id, func.count())
        .where(BastItem.organization_id == ctx.organization_id, BastItem.bast_id.in_(bast_ids))
        .group_by(BastItem.bast_id)
    )
    return {key: count for key, count in db.execute(stmt)}


def list_bast(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    status: DocStatus | None,
    kind: BastKind | None,
    spk_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    sort: str | None,
) -> tuple[list[Bast], int]:
    stmt = select(Bast).where(Bast.organization_id == ctx.organization_id)
    if q:
        term = f"%{escape_like(q)}%"
        stmt = stmt.where(or_(Bast.number.ilike(term), Bast.title.ilike(term)))
    if status:
        stmt = stmt.where(Bast.status == status)
    if kind:
        stmt = stmt.where(Bast.kind == kind)
    if spk_id:
        stmt = stmt.where(Bast.spk_id == spk_id)
    if project_id:
        stmt = stmt.where(
            Bast.spk_id.in_(
                select(Spk.id).where(
                    Spk.project_id == project_id, Spk.organization_id == ctx.organization_id
                )
            )
        )
    return paginate(db, apply_sort(stmt, sort, SORT, default="-created_at"), params)


def _lock_spk(db: Session, ctx: RequestContext, spk_id: uuid.UUID) -> Spk:
    """Serializes BAST changes per SPK (delivery totals are checked under this lock)."""
    spk = spk_service.get(db, ctx, spk_id, lock=True)
    if spk.status is not DocStatus.ISSUED:
        raise ConflictError(
            "BAST hanya dapat dibuat dan diproses untuk SPK yang sudah terbit.",
            details={"spk_status": spk.status.value},
        )
    return spk


def _require_single_final(
    db: Session, ctx: RequestContext, spk: Spk, bast_id: uuid.UUID | None
) -> None:
    final = final_of(db, ctx, spk.id)
    if final is not None and final.id != bast_id:
        raise ConflictError(
            "SPK ini sudah memiliki BAST serah terima akhir.",
            details={"bast_id": str(final.id), "number": final.number},
        )


# --------------------------------------------------------------------------- authoring


def create(db: Session, ctx: RequestContext, payload: BastCreate) -> Bast:
    spk = _lock_spk(db, ctx, payload.spk_id)
    if payload.kind is BastKind.FINAL:
        _require_single_final(db, ctx, spk, None)
    settings = documents.settings_row(db, ctx)
    label = BAST_KIND_LABELS[payload.kind]
    bast = Bast(
        organization_id=ctx.organization_id,
        status=DocStatus.DRAFT,
        kind=payload.kind,
        spk_id=spk.id,
        title=(payload.title or f"{label} · {spk.title}")[:300],
        location=spk.location,
        terms=settings.bast_terms if settings else None,
        created_by_id=ctx.user_id,
    )
    if payload.prefill_remaining:
        position = 0
        for row in progress.progress(db, ctx, spk):
            # What is neither handed over nor already in another BAST still being processed.
            available = row.remaining - row.pending
            if available > 0:
                position += 1
                bast.items.append(
                    BastItem(
                        organization_id=ctx.organization_id,
                        position=position,
                        rab_item_id=row.item.id,
                        description=row.item.name[:500],
                        quantity=available,
                        unit=row.item.unit,
                    )
                )
    db.add(bast)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if payload.kind is BastKind.FINAL:  # a final BAST raced in (partial unique index)
            raise ConflictError("SPK ini sudah memiliki BAST serah terima akhir.") from None
        raise
    common.record_audit(
        db,
        ctx,
        "bast.create",
        ENTITY,
        bast.id,
        f"{label} untuk {spk.number}",
        {"items": {"from": None, "to": len(bast.items)}},
    )
    db.commit()
    return get(db, ctx, bast.id)


def _require_draft(bast: Bast, version: int | None = None) -> None:
    if bast.status is not DocStatus.DRAFT:
        raise ConflictError("BAST hanya dapat diubah saat berstatus draft.")
    if version is not None and version != bast.version:
        raise VersionConflictError(details={"current_version": bast.version})


def _lines(items: list[BastItemIn]) -> list[tuple[uuid.UUID | None, Decimal, str]]:
    return [(i.rab_item_id, i.quantity, i.unit) for i in items]


def _stored_lines(bast: Bast) -> list[tuple[uuid.UUID | None, Decimal, str]]:
    return [(i.rab_item_id, i.quantity, i.unit) for i in bast.items]


def update(db: Session, ctx: RequestContext, bast_id: uuid.UUID, payload: BastUpdate) -> Bast:
    bast = get(db, ctx, bast_id, lock=True)
    _require_draft(bast, payload.version)
    spk = _lock_spk(db, ctx, bast.spk_id)
    if payload.handover_date and payload.handover_date > common.today():
        raise BusinessValidationError(
            "Tanggal serah terima tidak boleh di masa depan.",
            details=[{"loc": ["body", "handover_date"], "msg": "Tidak boleh di masa depan."}],
        )
    before: dict[str, Any] = {f: getattr(bast, f) for f in EDIT_FIELDS}
    for field in EDIT_FIELDS:
        setattr(bast, field, getattr(payload, field))
    changes: dict[str, Any] = {
        f: {"from": before[f], "to": getattr(bast, f)}
        for f in EDIT_FIELDS
        if before[f] != getattr(bast, f)
    }
    if payload.items is not None:
        progress.check_lines(db, ctx, spk, bast.id, _lines(payload.items))
        old = [f"{i.description}: {i.quantity} {i.unit}" for i in bast.items]
        bast.items.clear()
        db.flush()
        for position, item in enumerate(payload.items, start=1):
            bast.items.append(
                BastItem(
                    organization_id=ctx.organization_id,
                    position=position,
                    rab_item_id=item.rab_item_id,
                    description=item.description,
                    quantity=item.quantity,
                    unit=item.unit,
                    condition=item.condition,
                )
            )
        new = [f"{i.description}: {i.quantity} {i.unit}" for i in payload.items]
        if old != new:
            changes["items"] = {"from": old or None, "to": new or None}
        bast.updated_at = common.now()  # bumps `version`: the lines are part of the record
    if changes:
        db.flush()
        common.record_audit(db, ctx, "bast.update", ENTITY, bast.id, bast.title, changes)
    db.commit()
    return get(db, ctx, bast_id)


def missing_for_submit(bast: Bast) -> list[dict[str, Any]]:
    required = {
        "handover_date": "Tanggal serah terima wajib diisi.",
        "delivered_by_name": "Nama pihak yang menyerahkan wajib diisi.",
        "received_by_name": "Nama pihak yang menerima wajib diisi.",
    }
    missing = [
        {"loc": ["body", field], "msg": msg}
        for field, msg in required.items()
        if not getattr(bast, field)
    ]
    if not bast.items:
        missing.append({"loc": ["body", "items"], "msg": "Tambahkan minimal satu baris."})
    return missing


def transition(
    db: Session, ctx: RequestContext, bast_id: uuid.UUID, action: Action, note: str | None
) -> Bast:
    bast = get(db, ctx, bast_id, lock=True)
    if action is Action.SUBMIT:
        spk = _lock_spk(db, ctx, bast.spk_id)
        missing = missing_for_submit(bast)
        if missing:
            raise BusinessValidationError("Lengkapi BAST sebelum diajukan.", details=missing)
        if bast.handover_date and bast.handover_date > common.today():
            raise BusinessValidationError("Tanggal serah terima tidak boleh di masa depan.")
        progress.check_lines(db, ctx, spk, bast.id, _stored_lines(bast))
    before = common.apply_transition(db, ctx, bast, ENTITY, action, note, write=WRITE)
    db.flush()
    common.record_audit(
        db,
        ctx,
        f"bast.{action.value}",
        ENTITY,
        bast.id,
        bast.number or bast.title,
        {"status": {"from": before.value, "to": bast.status.value}},
    )
    db.commit()
    return get(db, ctx, bast_id)


def delete(db: Session, ctx: RequestContext, bast_id: uuid.UUID) -> None:
    bast = get(db, ctx, bast_id, lock=True)
    if bast.status not in DELETABLE:
        raise ConflictError("Hanya BAST draft atau ditolak yang dapat dihapus.")
    common.record_audit(db, ctx, "bast.delete", ENTITY, bast.id, bast.title)
    db.delete(bast)
    db.commit()


# --------------------------------------------------------------------------- documents


def _snapshot(
    db: Session, ctx: RequestContext, bast: Bast, spk: Spk, issuance: Issuance | None
) -> dict[str, Any]:
    try:
        return build_bast_snapshot(
            organization=ctx.organization,
            settings_row=documents.settings_row(db, ctx),
            letterhead=documents.letterhead_row(db, ctx),
            bast=bast,
            spk=spk,
            contract=progress.contract_items(db, ctx, spk),
            delivered_before=progress.handed_over(
                db, ctx, spk.id, (DocStatus.ISSUED,), exclude_bast_id=bast.id
            ),
            approvals=common.approvals_of(db, ctx, ENTITY, bast.id),
            issuance=issuance,
            generated_at=issuance.issued_at if issuance else common.now(),
        )
    except SnapshotIntegrityError as exc:
        raise ConflictError(str(exc)) from None


def preview_pdf(db: Session, ctx: RequestContext, bast_id: uuid.UUID) -> RenderedFile:
    bast = get(db, ctx, bast_id)
    snapshot = _snapshot(db, ctx, bast, bast.spk, None)
    content = render_bast_pdf(snapshot, None, documents.letterhead_png(db, ctx, snapshot))
    name = safe_filename(f"PRATINJAU_{bast.number or 'BAST'}_{bast.title}")
    return RenderedFile(f"{name}.pdf", CONTENT_TYPES[FileFormat.PDF], content)


@dataclass(frozen=True)
class Issued:
    bast: Bast
    document: IssuedDocument
    created: bool


def issue(
    db: Session, ctx: RequestContext, bast_id: uuid.UUID, idempotency_key: str | None
) -> Issued:
    bast = get(db, ctx, bast_id, lock=True)
    if idempotency_key and (existing := documents.find_by_key(db, ctx, idempotency_key)):
        if existing.bast_id != bast.id:
            raise IdempotencyKeyReusedError(details={"document_id": str(existing.id)})
        return Issued(bast, existing, False)
    if bast.status is DocStatus.ISSUED:
        raise AlreadyIssuedError("BAST ini sudah diterbitkan.")
    if bast.status is not DocStatus.APPROVED:
        raise ConflictError(
            "Hanya BAST yang sudah disetujui yang dapat diterbitkan.",
            details={"status": bast.status.value},
        )
    # Under the SPK lock: no other BAST of this SPK can be issued until this transaction ends.
    spk = _lock_spk(db, ctx, bast.spk_id)
    progress.check_lines(db, ctx, spk, bast.id, _stored_lines(bast))
    if bast.handover_date is None or bast.handover_date > common.today():
        raise BusinessValidationError(
            "Tanggal serah terima harus diisi dan tidak boleh di masa depan. "
            "Kembalikan ke draft untuk mengubahnya."
        )
    year = common.today().year
    bast.number = format_number("BAST", year, next_value(db, ctx.organization_id, "bast", year))
    bast.status = DocStatus.ISSUED
    issued_at = common.now()
    snapshot = _snapshot(db, ctx, bast, spk, Issuance(bast.number, issued_at, ctx.user.full_name))
    digest = snapshot_sha256(snapshot)
    try:
        document = documents.store_document(
            db,
            ctx,
            doc_type=DocumentType.BAST,
            number=bast.number,
            title=bast.title,
            project_id=spk.project_id,
            currency=spk.currency,
            total_amount=Decimal("0.00"),  # a handover record carries no amount
            snapshot=snapshot,
            digest=digest,
            files={
                FileFormat.PDF: render_bast_pdf(
                    snapshot, digest, documents.letterhead_png(db, ctx, snapshot)
                )
            },
            idempotency_key=idempotency_key,
            issued_at=issued_at,
            sources={"bast_id": bast.id},
            summary=f"{bast.number} · {bast.title}",
        )
    except IntegrityError:
        db.rollback()
        existing = documents.find_by_key(db, ctx, idempotency_key) if idempotency_key else None
        if existing is not None and existing.bast_id == bast_id:
            return Issued(get(db, ctx, bast_id), existing, False)
        raise
    db.commit()
    return Issued(get(db, ctx, bast_id), documents.get_document(db, ctx, document.id), True)


def void(db: Session, ctx: RequestContext, bast_id: uuid.UUID, reason: str) -> Bast:
    if not ctx.can(Permission.DOCUMENTS_ISSUE):
        raise PermissionDeniedError()
    bast = get(db, ctx, bast_id, lock=True)
    if bast.status is not DocStatus.ISSUED:
        raise ConflictError("Hanya BAST terbit yang dapat dibatalkan; draft cukup dihapus.")
    bast.status = DocStatus.VOID
    bast.voided_at = common.now()
    bast.voided_by_id = ctx.user_id
    bast.void_reason = reason
    documents.void_active(db, ctx, reason, bast_id=bast.id)
    db.flush()
    common.record_audit(
        db,
        ctx,
        "bast.void",
        ENTITY,
        bast.id,
        bast.number or bast.title,
        {"status": {"from": "issued", "to": "void"}, "void_reason": {"from": None, "to": reason}},
    )
    db.commit()
    return get(db, ctx, bast_id)
