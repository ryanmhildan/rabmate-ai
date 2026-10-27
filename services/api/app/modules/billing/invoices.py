"""Invoices: per payment term of an accepted quotation, or manual; workflow, issuance, voiding.

Numbers (INV-YYYY-NNNN) are assigned at issuance so drafts that are deleted leave no gaps.
Term invoices copy the schedule's figures and cannot be edited line by line; manual invoices are
recalculated with the RAB calculation rules on every change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
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
from app.modules.billing.invoicing import PaymentState, line_amount, manual_totals
from app.modules.billing.models import (
    ClientResponse,
    DocStatus,
    Invoice,
    InvoiceItem,
    InvoiceKind,
    PaymentTerm,
    Quotation,
    TermBasis,
)
from app.modules.billing.schemas import InvoiceCreate, InvoiceUpdate
from app.modules.billing.snapshots import build_invoice_snapshot
from app.modules.billing.workflow import DELETABLE, Action
from app.modules.documents import service as documents
from app.modules.documents.models import DocumentType, FileFormat, IssuedDocument
from app.modules.documents.render_billing import render_invoice_pdf
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
from app.modules.rab.calculation import CalculationError

ENTITY = "invoice"
WRITE = Permission.FINANCE_WRITE
SORT = {
    "created_at": Invoice.created_at,
    "due_date": Invoice.due_date,
    "number": Invoice.number,
    "grand_total": Invoice.grand_total,
}


def get(db: Session, ctx: RequestContext, invoice_id: uuid.UUID, *, lock: bool = False) -> Invoice:
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.organization_id == ctx.organization_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=Invoice)
    invoice = db.execute(stmt).unique().scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Invoice tidak ditemukan.")
    return invoice


def quotation_of(db: Session, invoice: Invoice) -> Quotation | None:
    if invoice.quotation_id is None:
        return None
    return db.execute(
        select(Quotation).where(
            Quotation.id == invoice.quotation_id,
            Quotation.organization_id == invoice.organization_id,
        )
    ).scalar_one()


def list_invoices(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    status: DocStatus | None,
    payment_state: PaymentState | None,
    overdue: bool | None,
    project_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    quotation_id: uuid.UUID | None,
    sort: str | None,
) -> tuple[list[Invoice], int]:
    stmt = select(Invoice).where(Invoice.organization_id == ctx.organization_id)
    if q:
        term = f"%{escape_like(q)}%"
        stmt = stmt.where(or_(Invoice.number.ilike(term), Invoice.title.ilike(term)))
    if status:
        stmt = stmt.where(Invoice.status == status)
    if payment_state:
        issued = Invoice.status == DocStatus.ISSUED
        stmt = stmt.where(
            {
                PaymentState.UNPAID: and_(issued, Invoice.amount_paid == 0),
                PaymentState.PARTIAL: and_(
                    issued, Invoice.amount_paid > 0, Invoice.amount_paid < Invoice.grand_total
                ),
                PaymentState.PAID: and_(issued, Invoice.amount_paid >= Invoice.grand_total),
            }[payment_state]
        )
    if overdue is not None:
        condition = and_(
            Invoice.status == DocStatus.ISSUED,
            Invoice.amount_paid < Invoice.grand_total,
            Invoice.due_date < common.today(),
        )
        stmt = stmt.where(condition if overdue else ~condition)
    if project_id:
        stmt = stmt.where(Invoice.project_id == project_id)
    if client_id:
        stmt = stmt.where(Invoice.client_id == client_id)
    if quotation_id:
        stmt = stmt.where(Invoice.quotation_id == quotation_id)
    return paginate(db, apply_sort(stmt, sort, SORT, default="-created_at"), params)


# --------------------------------------------------------------------------- creation


def create_manual(db: Session, ctx: RequestContext, payload: InvoiceCreate) -> Invoice:
    project = db.execute(
        select(Project).where(
            Project.id == payload.project_id, Project.organization_id == ctx.organization_id
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Proyek tidak ditemukan.")
    if project.client_id is None:
        raise BusinessValidationError(
            "Proyek belum memiliki klien. Tentukan klien proyek sebelum membuat invoice."
        )
    invoice = Invoice(
        organization_id=ctx.organization_id,
        kind=InvoiceKind.MANUAL,
        status=DocStatus.DRAFT,
        project_id=project.id,
        client_id=project.client_id,
        title=payload.title,
        due_date=payload.due_date,
        notes=payload.notes,
        currency=project.currency,
        tax_label=project.tax_label,
        tax_rate_percent=project.tax_rate_percent,
        created_by_id=ctx.user_id,
    )
    db.add(invoice)
    db.flush()
    common.record_audit(db, ctx, "invoice.create", ENTITY, invoice.id, invoice.title)
    db.commit()
    return get(db, ctx, invoice.id)


def create_for_term(
    db: Session, ctx: RequestContext, quotation_id: uuid.UUID, term_id: uuid.UUID
) -> Invoice:
    quotation = db.execute(
        select(Quotation)
        .where(Quotation.id == quotation_id, Quotation.organization_id == ctx.organization_id)
        .with_for_update(of=Quotation)
    ).scalar_one_or_none()
    if quotation is None:
        raise NotFoundError("Penawaran tidak ditemukan.")
    term = next((t for t in quotation.payment_terms if t.id == term_id), None)
    if term is None:
        raise NotFoundError("Termin tidak ditemukan.")
    if (
        quotation.status is not DocStatus.ISSUED
        or quotation.client_response is not ClientResponse.ACCEPTED
    ):
        raise ConflictError("Termin hanya dapat ditagih dari penawaran terbit yang diterima klien.")
    existing = (
        db.execute(
            select(Invoice).where(
                Invoice.payment_term_id == term.id,
                Invoice.organization_id == ctx.organization_id,
                Invoice.status != DocStatus.VOID,
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if existing is not None:
        raise ConflictError(
            "Termin ini sudah memiliki invoice.", details={"invoice_id": str(existing.id)}
        )
    project = quotation.project
    if project.client_id is None:
        raise BusinessValidationError("Proyek belum memiliki klien.")
    portion = (
        f"{term.percent.normalize():f}% dari nilai kontrak sebelum pajak"
        if term.basis is TermBasis.PERCENT and term.percent is not None
        else "nilai tetap sebelum pajak"
    )
    invoice = Invoice(
        organization_id=ctx.organization_id,
        kind=InvoiceKind.TERM,
        status=DocStatus.DRAFT,
        project_id=project.id,
        client_id=project.client_id,
        quotation_id=quotation.id,
        payment_term_id=term.id,
        title=f"{term.name} · {quotation.subject}"[:300],
        due_date=term.due_date,
        currency=quotation.currency,
        tax_label=quotation.tax_label,
        tax_rate_percent=quotation.tax_rate_percent,
        subtotal=term.amount,
        tax_amount=term.tax_amount,
        grand_total=term.total_amount,
        created_by_id=ctx.user_id,
    )
    invoice.items.append(
        InvoiceItem(
            organization_id=ctx.organization_id,
            position=1,
            description=f"{term.name} ({portion}) · {quotation.number}"[:500],
            quantity=Decimal(1),
            unit="ls",
            unit_price=term.amount,
            amount=term.amount,
        )
    )
    db.add(invoice)
    try:
        db.flush()
    except IntegrityError:  # a concurrent request created the invoice for this term
        db.rollback()
        raise ConflictError("Termin ini sudah memiliki invoice.") from None
    common.record_audit(
        db,
        ctx,
        "invoice.create",
        ENTITY,
        invoice.id,
        f"{invoice.title} ({quotation.number})",
        {"grand_total": {"from": None, "to": invoice.grand_total}},
    )
    db.commit()
    return get(db, ctx, invoice.id)


# --------------------------------------------------------------------------- editing


def update(
    db: Session, ctx: RequestContext, invoice_id: uuid.UUID, payload: InvoiceUpdate
) -> Invoice:
    invoice = get(db, ctx, invoice_id, lock=True)
    if invoice.status is not DocStatus.DRAFT:
        raise ConflictError("Invoice hanya dapat diubah saat berstatus draft.")
    if payload.version != invoice.version:
        raise VersionConflictError(details={"current_version": invoice.version})
    if (payload.tax_label is None) != (payload.tax_rate_percent is None):
        raise BusinessValidationError("Label dan tarif pajak diisi bersamaan atau dikosongkan.")
    before = {
        "title": invoice.title,
        "due_date": invoice.due_date,
        "grand_total": invoice.grand_total,
    }
    invoice.title = payload.title
    invoice.due_date = payload.due_date
    invoice.notes = payload.notes
    if invoice.kind is InvoiceKind.MANUAL:
        invoice.tax_label = payload.tax_label
        invoice.tax_rate_percent = payload.tax_rate_percent
        if payload.items is not None:
            invoice.items.clear()
            db.flush()
            for position, line in enumerate(payload.items, start=1):
                invoice.items.append(
                    InvoiceItem(
                        organization_id=ctx.organization_id,
                        position=position,
                        description=line.description,
                        quantity=line.quantity,
                        unit=line.unit,
                        unit_price=line.unit_price,
                        amount=line_amount(line.quantity, line.unit_price),
                    )
                )
        _recalculate(invoice)
    elif payload.items is not None or (
        (payload.tax_label, payload.tax_rate_percent)
        != (invoice.tax_label, invoice.tax_rate_percent)
    ):
        raise BusinessValidationError(
            "Baris dan pajak invoice termin mengikuti jadwal pembayaran dan tidak dapat diubah."
        )
    invoice.updated_at = common.now()
    db.flush()
    after = {
        "title": invoice.title,
        "due_date": invoice.due_date,
        "grand_total": invoice.grand_total,
    }
    changes = {k: {"from": before[k], "to": after[k]} for k in before if before[k] != after[k]}
    common.record_audit(
        db, ctx, "invoice.update", ENTITY, invoice.id, invoice.title, changes or None
    )
    db.commit()
    return get(db, ctx, invoice_id)


def _recalculate(invoice: Invoice) -> None:
    try:
        totals = manual_totals(
            [(i.quantity, i.unit_price) for i in invoice.items], invoice.tax_rate_percent
        )
    except CalculationError as exc:
        raise BusinessValidationError(exc.message, details={"code": exc.code}) from None
    invoice.subtotal = totals.subtotal
    invoice.tax_amount = totals.tax_amount
    invoice.grand_total = totals.grand_total


def transition(
    db: Session, ctx: RequestContext, invoice_id: uuid.UUID, action: Action, note: str | None
) -> Invoice:
    invoice = get(db, ctx, invoice_id, lock=True)
    if action is Action.SUBMIT:
        problems = []
        if not invoice.items:
            problems.append("Invoice belum memiliki baris tagihan.")
        if invoice.grand_total <= 0:
            problems.append("Total invoice harus lebih dari 0.")
        if invoice.due_date is None:
            problems.append("Tanggal jatuh tempo wajib diisi.")
        elif invoice.due_date < common.today():
            problems.append("Tanggal jatuh tempo sudah lewat.")
        if problems:
            raise BusinessValidationError(" ".join(problems), details={"problems": problems})
    before = common.apply_transition(db, ctx, invoice, ENTITY, action, note, write=WRITE)
    db.flush()
    common.record_audit(
        db,
        ctx,
        f"invoice.{action.value}",
        ENTITY,
        invoice.id,
        invoice.number or invoice.title,
        {"status": {"from": before.value, "to": invoice.status.value}},
    )
    db.commit()
    return get(db, ctx, invoice_id)


def delete(db: Session, ctx: RequestContext, invoice_id: uuid.UUID) -> None:
    invoice = get(db, ctx, invoice_id, lock=True)
    if invoice.status not in DELETABLE:
        raise ConflictError("Hanya invoice draft atau ditolak yang dapat dihapus.")
    common.record_audit(db, ctx, "invoice.delete", ENTITY, invoice.id, invoice.title)
    db.delete(invoice)
    db.commit()


# --------------------------------------------------------------------------- documents


def _snapshot(
    db: Session,
    ctx: RequestContext,
    invoice: Invoice,
    issuance: Issuance | None,
    issue_date: date | None,
) -> dict[str, Any]:
    try:
        return build_invoice_snapshot(
            organization=ctx.organization,
            settings_row=documents.settings_row(db, ctx),
            letterhead=documents.letterhead_row(db, ctx),
            invoice=invoice,
            quotation=quotation_of(db, invoice),
            approvals=common.approvals_of(db, ctx, ENTITY, invoice.id),
            issuance=issuance,
            issue_date=issue_date,
            generated_at=issuance.issued_at if issuance else common.now(),
        )
    except SnapshotIntegrityError as exc:
        raise ConflictError(str(exc)) from None


def preview_pdf(db: Session, ctx: RequestContext, invoice_id: uuid.UUID) -> RenderedFile:
    invoice = get(db, ctx, invoice_id)
    snapshot = _snapshot(db, ctx, invoice, None, invoice.issue_date)
    content = render_invoice_pdf(snapshot, None, documents.letterhead_png(db, ctx, snapshot))
    name = safe_filename(f"PRATINJAU_{invoice.number or 'invoice'}_{invoice.title}"[:80])
    return RenderedFile(f"{name}.pdf", CONTENT_TYPES[FileFormat.PDF], content)


@dataclass(frozen=True)
class Issued:
    invoice: Invoice
    document: IssuedDocument
    created: bool


def issue(
    db: Session, ctx: RequestContext, invoice_id: uuid.UUID, idempotency_key: str | None
) -> Issued:
    invoice = get(db, ctx, invoice_id, lock=True)
    if idempotency_key and (existing := documents.find_by_key(db, ctx, idempotency_key)):
        if existing.invoice_id != invoice.id:
            raise IdempotencyKeyReusedError(details={"document_id": str(existing.id)})
        return Issued(invoice, existing, False)
    if invoice.status is DocStatus.ISSUED:
        raise AlreadyIssuedError("Invoice ini sudah diterbitkan.")
    if invoice.status is not DocStatus.APPROVED:
        raise ConflictError(
            "Hanya invoice yang sudah disetujui yang dapat diterbitkan.",
            details={"status": invoice.status.value},
        )
    issue_date = common.today()
    if invoice.due_date is None or invoice.due_date < issue_date:
        raise BusinessValidationError(
            "Tanggal jatuh tempo harus sama dengan atau setelah tanggal terbit. "
            "Kembalikan ke draft untuk mengubahnya."
        )
    year = issue_date.year
    invoice.number = format_number(
        "INV", year, next_value(db, ctx.organization_id, "invoice", year)
    )
    invoice.issue_date = issue_date
    invoice.status = DocStatus.ISSUED
    issued_at = common.now()
    snapshot = _snapshot(
        db, ctx, invoice, Issuance(invoice.number, issued_at, ctx.user.full_name), issue_date
    )
    digest = snapshot_sha256(snapshot)
    try:
        document = documents.store_document(
            db,
            ctx,
            doc_type=DocumentType.INVOICE,
            number=invoice.number,
            title=invoice.title,
            project_id=invoice.project_id,
            currency=invoice.currency,
            total_amount=invoice.grand_total,
            snapshot=snapshot,
            digest=digest,
            files={
                FileFormat.PDF: render_invoice_pdf(
                    snapshot, digest, documents.letterhead_png(db, ctx, snapshot)
                )
            },
            idempotency_key=idempotency_key,
            issued_at=issued_at,
            sources={"invoice_id": invoice.id},
            summary=f"{invoice.number} · {invoice.title}",
        )
    except IntegrityError:
        db.rollback()
        existing = documents.find_by_key(db, ctx, idempotency_key) if idempotency_key else None
        if existing is not None and existing.invoice_id == invoice_id:
            return Issued(get(db, ctx, invoice_id), existing, False)
        raise
    db.commit()
    return Issued(get(db, ctx, invoice_id), documents.get_document(db, ctx, document.id), True)


def void(db: Session, ctx: RequestContext, invoice_id: uuid.UUID, reason: str) -> Invoice:
    if not ctx.can(Permission.DOCUMENTS_ISSUE):
        raise PermissionDeniedError()
    invoice = get(db, ctx, invoice_id, lock=True)
    if invoice.status is not DocStatus.ISSUED:
        raise ConflictError("Hanya invoice terbit yang dapat dibatalkan; draft cukup dihapus.")
    if invoice.amount_paid > 0:
        raise ConflictError(
            "Invoice sudah menerima pembayaran. Batalkan pembayarannya terlebih dahulu."
        )
    invoice.status = DocStatus.VOID
    invoice.voided_at = common.now()
    invoice.voided_by_id = ctx.user_id
    invoice.void_reason = reason
    documents.void_active(db, ctx, reason, invoice_id=invoice.id)
    db.flush()
    common.record_audit(
        db,
        ctx,
        "invoice.void",
        ENTITY,
        invoice.id,
        invoice.number or invoice.title,
        {"status": {"from": "issued", "to": "void"}, "void_reason": {"from": None, "to": reason}},
    )
    db.commit()
    return get(db, ctx, invoice_id)


def term_of(invoice: Invoice) -> PaymentTerm | None:
    return invoice.payment_term
