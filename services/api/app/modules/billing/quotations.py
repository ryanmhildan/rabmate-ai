"""Quotations (penawaran) from approved RAB versions, their payment schedule, and issuance."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

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
from app.modules.billing.models import (
    ClientResponse,
    DocStatus,
    Invoice,
    PaymentTerm,
    Quotation,
)
from app.modules.billing.schemas import QuotationCreate, QuotationUpdate, TermIn
from app.modules.billing.snapshots import build_quotation_snapshot
from app.modules.billing.terms import TermsError, TermSpec, allocate
from app.modules.billing.workflow import DELETABLE, Action
from app.modules.documents import service as documents
from app.modules.documents.models import DocumentType, FileFormat, IssuedDocument
from app.modules.documents.render_billing import render_quotation_pdf
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
from app.modules.projects.models import Project
from app.modules.rab.models import RabDocument, RabStatus, RabVersion
from app.modules.workorders.models import Spk

ENTITY = "quotation"
WRITE = Permission.RAB_WRITE
DEFAULT_VALIDITY_DAYS = 30
SORT = {
    "created_at": Quotation.created_at,
    "number": Quotation.number,
    "grand_total": Quotation.grand_total,
}
EDIT_FIELDS = ("subject", "valid_until", "introduction", "scope", "terms", "notes")


# --------------------------------------------------------------------------- loading


def get(
    db: Session, ctx: RequestContext, quotation_id: uuid.UUID, *, lock: bool = False
) -> Quotation:
    stmt = (
        select(Quotation)
        .where(Quotation.id == quotation_id, Quotation.organization_id == ctx.organization_id)
        .options(joinedload(Quotation.rab_version).joinedload(RabVersion.rab))
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=Quotation)
    quotation = db.execute(stmt).unique().scalar_one_or_none()
    if quotation is None:
        raise NotFoundError("Penawaran tidak ditemukan.")
    return quotation


def source_version(
    db: Session, ctx: RequestContext, quotation: Quotation
) -> tuple[RabDocument, RabVersion]:
    version = db.execute(
        select(RabVersion)
        .where(
            RabVersion.id == quotation.rab_version_id,
            RabVersion.organization_id == ctx.organization_id,
        )
        .options(selectinload(RabVersion.items))
    ).scalar_one()
    return version.rab, version


def active_invoices(db: Session, quotation: Quotation) -> list[Invoice]:
    return list(
        db.execute(
            select(Invoice).where(
                Invoice.quotation_id == quotation.id,
                Invoice.organization_id == quotation.organization_id,
                Invoice.status != DocStatus.VOID,
            )
        )
        .unique()
        .scalars()
    )


def active_spk(db: Session, quotation: Quotation) -> Spk | None:
    """The SPK made from this quotation (any status except void)."""
    return (
        db.execute(
            select(Spk).where(
                Spk.quotation_id == quotation.id,
                Spk.organization_id == quotation.organization_id,
                Spk.status != DocStatus.VOID,
            )
        )
        .unique()
        .scalar_one_or_none()
    )


def is_expired(quotation: Quotation) -> bool:
    return (
        quotation.status is DocStatus.ISSUED
        and quotation.client_response is None
        and quotation.valid_until is not None
        and quotation.valid_until < common.today()
    )


def list_quotations(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    status: DocStatus | None,
    project_id: uuid.UUID | None,
    rab_id: uuid.UUID | None,
    client_response: ClientResponse | None,
    sort: str | None,
) -> tuple[list[Quotation], int]:
    stmt = (
        select(Quotation)
        .where(Quotation.organization_id == ctx.organization_id)
        .options(joinedload(Quotation.rab_version).joinedload(RabVersion.rab))
    )
    if q:
        term = f"%{escape_like(q)}%"
        stmt = stmt.where(or_(Quotation.number.ilike(term), Quotation.subject.ilike(term)))
    if status:
        stmt = stmt.where(Quotation.status == status)
    if project_id:
        stmt = stmt.where(Quotation.project_id == project_id)
    if rab_id:
        stmt = stmt.where(
            Quotation.rab_version_id.in_(
                select(RabVersion.id).where(
                    RabVersion.rab_id == rab_id, RabVersion.organization_id == ctx.organization_id
                )
            )
        )
    if client_response:
        stmt = stmt.where(Quotation.client_response == client_response)
    return paginate(db, apply_sort(stmt, sort, SORT, default="-created_at"), params)


# --------------------------------------------------------------------------- authoring


def create(db: Session, ctx: RequestContext, payload: QuotationCreate) -> Quotation:
    version = db.execute(
        select(RabVersion).where(
            RabVersion.id == payload.rab_version_id,
            RabVersion.organization_id == ctx.organization_id,
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError("Versi RAB tidak ditemukan.")
    if version.status is not RabStatus.APPROVED:
        raise ConflictError("Penawaran hanya dapat dibuat dari versi RAB yang disetujui.")
    rab = version.rab
    project: Project = rab.project
    if project.client_id is None:
        raise BusinessValidationError(
            "Proyek belum memiliki klien. Tentukan klien proyek sebelum membuat penawaran."
        )
    year = common.today().year
    settings = documents.settings_row(db, ctx)
    quotation = Quotation(
        organization_id=ctx.organization_id,
        number=format_number("PNW", year, next_value(db, ctx.organization_id, "quotation", year)),
        project_id=project.id,
        rab_version_id=version.id,
        status=DocStatus.DRAFT,
        subject=payload.subject or f"Penawaran {rab.title}"[:300],
        valid_until=common.today() + timedelta(days=DEFAULT_VALIDITY_DAYS),
        terms=settings.rab_terms if settings else None,
        currency=version.currency,
        subtotal=version.subtotal,
        discount_amount=version.discount_amount,
        taxable_base=version.taxable_base,
        tax_label=version.tax_label,
        tax_rate_percent=version.tax_rate_percent,
        tax_amount=version.tax_amount,
        grand_total=version.grand_total,
        created_by_id=ctx.user_id,
    )
    db.add(quotation)
    db.flush()
    common.record_audit(
        db,
        ctx,
        "quotation.create",
        ENTITY,
        quotation.id,
        f"{quotation.number} dari {rab.number} v{version.version_no}",
        {"grand_total": {"from": None, "to": quotation.grand_total}},
    )
    db.commit()
    return get(db, ctx, quotation.id)


def _require_draft(quotation: Quotation, version: int | None = None) -> None:
    if quotation.status is not DocStatus.DRAFT:
        raise ConflictError("Penawaran hanya dapat diubah saat berstatus draft.")
    if version is not None and version != quotation.version:
        raise VersionConflictError(details={"current_version": quotation.version})


def update(
    db: Session, ctx: RequestContext, quotation_id: uuid.UUID, payload: QuotationUpdate
) -> Quotation:
    quotation = get(db, ctx, quotation_id, lock=True)
    _require_draft(quotation, payload.version)
    before = {f: getattr(quotation, f) for f in EDIT_FIELDS}
    for field in EDIT_FIELDS:
        setattr(quotation, field, getattr(payload, field))
    changes = {
        f: {"from": before[f], "to": getattr(quotation, f)}
        for f in EDIT_FIELDS
        if before[f] != getattr(quotation, f)
    }
    if changes:
        db.flush()
        common.record_audit(
            db, ctx, "quotation.update", ENTITY, quotation.id, quotation.number, changes
        )
    db.commit()
    return get(db, ctx, quotation_id)


def set_terms(
    db: Session, ctx: RequestContext, quotation_id: uuid.UUID, version: int, terms: list[TermIn]
) -> Quotation:
    quotation = get(db, ctx, quotation_id, lock=True)
    _require_draft(quotation, version)
    try:
        allocated = allocate(
            quotation.taxable_base,
            quotation.tax_amount,
            [TermSpec(t.name, t.basis, t.value, t.due_date, t.description) for t in terms],
        )
    except TermsError as exc:
        details = None
        if exc.index is not None:
            details = [{"loc": ["body", "terms", exc.index, "value"], "msg": exc.message}]
        raise BusinessValidationError(exc.message, details=details) from None
    quotation.payment_terms.clear()
    db.flush()
    for position, term in enumerate(allocated, start=1):
        quotation.payment_terms.append(
            PaymentTerm(
                organization_id=ctx.organization_id,
                position=position,
                name=term.spec.name,
                basis=term.spec.basis,
                percent=term.percent,
                amount=term.amount,
                tax_amount=term.tax_amount,
                total_amount=term.total_amount,
                due_date=term.spec.due_date,
                description=term.spec.description,
            )
        )
    quotation.updated_at = common.now()  # bumps `version`: the schedule is part of the offer
    db.flush()
    common.record_audit(
        db,
        ctx,
        "quotation.terms",
        ENTITY,
        quotation.id,
        quotation.number,
        {
            "payment_terms": {
                "from": None,
                "to": [f"{t.spec.name}: {t.total_amount}" for t in allocated],
            }
        },
    )
    db.commit()
    return get(db, ctx, quotation_id)


def transition(
    db: Session, ctx: RequestContext, quotation_id: uuid.UUID, action: Action, note: str | None
) -> Quotation:
    quotation = get(db, ctx, quotation_id, lock=True)
    if action is Action.SUBMIT:
        if not quotation.payment_terms:
            raise BusinessValidationError("Tentukan jadwal pembayaran (termin) sebelum diajukan.")
        if sum(t.total_amount for t in quotation.payment_terms) != quotation.grand_total:
            raise BusinessValidationError("Jumlah termin tidak sama dengan total penawaran.")
        if quotation.valid_until is not None and quotation.valid_until < common.today():
            raise BusinessValidationError("Tanggal berlaku penawaran sudah lewat.")
    before = common.apply_transition(db, ctx, quotation, ENTITY, action, note, write=WRITE)
    db.flush()
    common.record_audit(
        db,
        ctx,
        f"quotation.{action.value}",
        ENTITY,
        quotation.id,
        quotation.number,
        {"status": {"from": before.value, "to": quotation.status.value}},
    )
    db.commit()
    return get(db, ctx, quotation_id)


def delete(db: Session, ctx: RequestContext, quotation_id: uuid.UUID) -> None:
    quotation = get(db, ctx, quotation_id, lock=True)
    if quotation.status not in DELETABLE:
        raise ConflictError("Hanya penawaran draft atau ditolak yang dapat dihapus.")
    common.record_audit(db, ctx, "quotation.delete", ENTITY, quotation.id, quotation.number)
    db.delete(quotation)
    db.commit()


# --------------------------------------------------------------------------- documents


def _snapshot(
    db: Session, ctx: RequestContext, quotation: Quotation, issuance: Issuance | None
) -> dict[str, Any]:
    rab, version = source_version(db, ctx, quotation)
    try:
        return build_quotation_snapshot(
            organization=ctx.organization,
            settings_row=documents.settings_row(db, ctx),
            letterhead=documents.letterhead_row(db, ctx),
            quotation=quotation,
            rab=rab,
            version=version,
            approvals=common.approvals_of(db, ctx, ENTITY, quotation.id),
            issuance=issuance,
            generated_at=issuance.issued_at if issuance else common.now(),
        )
    except SnapshotIntegrityError as exc:
        raise ConflictError(str(exc)) from None


def preview_pdf(db: Session, ctx: RequestContext, quotation_id: uuid.UUID) -> RenderedFile:
    quotation = get(db, ctx, quotation_id)
    snapshot = _snapshot(db, ctx, quotation, None)
    content = render_quotation_pdf(snapshot, None, documents.letterhead_png(db, ctx, snapshot))
    name = safe_filename(f"PRATINJAU_{quotation.number}")
    return RenderedFile(f"{name}.pdf", CONTENT_TYPES[FileFormat.PDF], content)


@dataclass(frozen=True)
class Issued:
    quotation: Quotation
    document: IssuedDocument
    created: bool


def issue(
    db: Session, ctx: RequestContext, quotation_id: uuid.UUID, idempotency_key: str | None
) -> Issued:
    quotation = get(db, ctx, quotation_id, lock=True)
    if idempotency_key and (existing := documents.find_by_key(db, ctx, idempotency_key)):
        if existing.quotation_id != quotation.id:
            raise IdempotencyKeyReusedError(details={"document_id": str(existing.id)})
        return Issued(quotation, existing, False)
    if quotation.status is DocStatus.ISSUED:
        raise AlreadyIssuedError("Penawaran ini sudah diterbitkan.")
    if quotation.status is not DocStatus.APPROVED:
        raise ConflictError(
            "Hanya penawaran yang sudah disetujui yang dapat diterbitkan.",
            details={"status": quotation.status.value},
        )
    issued_at = common.now()
    quotation.status = DocStatus.ISSUED  # before the snapshot: the document shows "Terbit"
    snapshot = _snapshot(
        db, ctx, quotation, Issuance(quotation.number, issued_at, ctx.user.full_name)
    )
    digest = snapshot_sha256(snapshot)
    try:
        document = documents.store_document(
            db,
            ctx,
            doc_type=DocumentType.QUOTATION,
            number=quotation.number,
            title=quotation.subject,
            project_id=quotation.project_id,
            currency=quotation.currency,
            total_amount=quotation.grand_total,
            snapshot=snapshot,
            digest=digest,
            files={
                FileFormat.PDF: render_quotation_pdf(
                    snapshot, digest, documents.letterhead_png(db, ctx, snapshot)
                )
            },
            idempotency_key=idempotency_key,
            issued_at=issued_at,
            sources={"quotation_id": quotation.id},
            summary=f"{quotation.number} · {quotation.subject}",
        )
    except IntegrityError:
        db.rollback()
        existing = documents.find_by_key(db, ctx, idempotency_key) if idempotency_key else None
        if existing is not None and existing.quotation_id == quotation_id:
            return Issued(get(db, ctx, quotation_id), existing, False)
        raise
    db.commit()
    return Issued(get(db, ctx, quotation_id), documents.get_document(db, ctx, document.id), True)


def respond(
    db: Session,
    ctx: RequestContext,
    quotation_id: uuid.UUID,
    response: ClientResponse,
    note: str | None,
) -> Quotation:
    quotation = get(db, ctx, quotation_id, lock=True)
    if quotation.status is not DocStatus.ISSUED:
        raise ConflictError("Tanggapan klien dicatat untuk penawaran yang sudah terbit.")
    if quotation.client_response is not response and active_invoices(db, quotation):
        raise ConflictError("Penawaran sudah memiliki invoice; tanggapan klien tidak dapat diubah.")
    if quotation.client_response is not response and active_spk(db, quotation):
        raise ConflictError("Penawaran sudah memiliki SPK; tanggapan klien tidak dapat diubah.")
    before = quotation.client_response
    quotation.client_response = response
    quotation.responded_at = common.now()
    quotation.response_note = note
    db.flush()
    common.record_audit(
        db,
        ctx,
        "quotation.respond",
        ENTITY,
        quotation.id,
        quotation.number,
        {"client_response": {"from": before.value if before else None, "to": response.value}},
    )
    db.commit()
    return get(db, ctx, quotation_id)


def void(db: Session, ctx: RequestContext, quotation_id: uuid.UUID, reason: str) -> Quotation:
    if not ctx.can(Permission.DOCUMENTS_ISSUE):
        raise PermissionDeniedError()
    quotation = get(db, ctx, quotation_id, lock=True)
    if quotation.status is not DocStatus.ISSUED:
        raise ConflictError("Hanya penawaran terbit yang dapat dibatalkan; draft cukup dihapus.")
    if active_invoices(db, quotation):
        raise ConflictError("Batalkan dulu invoice yang dibuat dari penawaran ini.")
    if active_spk(db, quotation):
        raise ConflictError("Batalkan atau hapus dulu SPK yang dibuat dari penawaran ini.")
    quotation.status = DocStatus.VOID
    quotation.voided_at = common.now()
    quotation.voided_by_id = ctx.user_id
    quotation.void_reason = reason
    documents.void_active(db, ctx, reason, quotation_id=quotation.id)
    db.flush()
    common.record_audit(
        db,
        ctx,
        "quotation.void",
        ENTITY,
        quotation.id,
        quotation.number,
        {"status": {"from": "issued", "to": "void"}, "void_reason": {"from": None, "to": reason}},
    )
    db.commit()
    return get(db, ctx, quotation_id)


def term_invoice_counts(db: Session, quotation: Quotation) -> dict[uuid.UUID, Invoice]:
    return {
        inv.payment_term_id: inv
        for inv in active_invoices(db, quotation)
        if inv.payment_term_id is not None
    }
