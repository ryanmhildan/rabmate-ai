from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.core.ratelimit import EXPENSIVE
from app.db.session import get_db
from app.modules.billing import common, invoices, payments, quotations, schemas
from app.modules.billing.invoicing import PaymentState, is_overdue, payment_state
from app.modules.billing.models import (
    ClientResponse,
    DocStatus,
    Invoice,
    InvoiceKind,
    Payment,
    PaymentAllocation,
    PaymentStatus,
    Quotation,
)
from app.modules.billing.workflow import DELETABLE, Action, allowed_actions
from app.modules.documents.router import IdempotencyKey, file_response
from app.modules.documents.schemas import DocumentOut
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import UserBrief
from app.modules.rab.schemas import ApprovalOut

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}
P = Permission

quotations_router = APIRouter(prefix="/quotations", tags=["billing"], responses=ERRORS)
invoices_router = APIRouter(prefix="/invoices", tags=["billing"], responses=ERRORS)
payments_router = APIRouter(prefix="/payments", tags=["billing"], responses=ERRORS)


def _user(user: Any) -> UserBrief | None:
    return UserBrief.model_validate(user) if user is not None else None


def _approvals(
    db: Session, ctx: RequestContext, entity: str, entity_id: uuid.UUID
) -> list[ApprovalOut]:
    return [ApprovalOut.model_validate(r) for r in common.approvals_of(db, ctx, entity, entity_id)]


# --------------------------------------------------------------------------- quotation mapping


def _quotation_item(q: Quotation) -> dict[str, Any]:
    project = q.project
    client = project.client
    return {
        "id": q.id,
        "number": q.number,
        "status": q.status,
        "subject": q.subject,
        "project": schemas.Brief(id=project.id, number=project.number, name=project.name),
        "client": schemas.Brief(id=client.id, number=client.code, name=client.name)
        if client
        else None,
        "rab": schemas.RefBrief(id=q.rab_version.rab.id, number=q.rab_version.rab.number),
        "rab_version_no": q.rab_version.version_no,
        "currency": q.currency,
        "grand_total": q.grand_total,
        "valid_until": q.valid_until,
        "expired": quotations.is_expired(q),
        "client_response": q.client_response,
        "created_at": q.created_at,
        "updated_at": q.updated_at,
    }


def term_rows(db: Session, q: Quotation) -> list[schemas.TermOut]:
    """Payment terms with the invoice made for each (also shown on the SPK page)."""
    billed = quotations.term_invoice_counts(db, q)
    return [
        schemas.TermOut(
            id=t.id,
            position=t.position,
            name=t.name,
            basis=t.basis,
            percent=t.percent,
            amount=t.amount,
            tax_amount=t.tax_amount,
            total_amount=t.total_amount,
            due_date=t.due_date,
            description=t.description,
            invoice=schemas.InvoiceBrief(
                id=billed[t.id].id,
                number=billed[t.id].number,
                status=billed[t.id].status,
                payment_state=payment_state(
                    billed[t.id].status, billed[t.id].grand_total, billed[t.id].amount_paid
                ),
            )
            if t.id in billed
            else None,
        )
        for t in q.payment_terms
    ]


def _quotation_out(db: Session, ctx: RequestContext, q: Quotation) -> schemas.QuotationOut:
    has_invoices = bool(quotations.active_invoices(db, q))
    spk = quotations.active_spk(db, q)
    accepted = q.client_response is ClientResponse.ACCEPTED
    terms = term_rows(db, q)
    issued = q.status is DocStatus.ISSUED
    return schemas.QuotationOut(
        **_quotation_item(q),
        introduction=q.introduction,
        scope=q.scope,
        terms=q.terms,
        notes=q.notes,
        subtotal=q.subtotal,
        discount_amount=q.discount_amount,
        taxable_base=q.taxable_base,
        tax_label=q.tax_label,
        tax_rate_percent=q.tax_rate_percent,
        tax_amount=q.tax_amount,
        payment_terms=terms,
        responded_at=q.responded_at,
        response_note=q.response_note,
        submitted_by=_user(q.submitted_by),
        submitted_at=q.submitted_at,
        decided_by=_user(q.decided_by),
        decided_at=q.decided_at,
        voided_at=q.voided_at,
        void_reason=q.void_reason,
        version=q.version,
        approvals=_approvals(db, ctx, quotations.ENTITY, q.id),
        allowed_actions=[
            a.value for a in allowed_actions(q.status, ctx.permissions, write=P.RAB_WRITE)
        ],
        editable=q.status is DocStatus.DRAFT and ctx.can(P.RAB_WRITE),
        can_issue=q.status is DocStatus.APPROVED and ctx.can(P.DOCUMENTS_ISSUE),
        can_respond=issued and ctx.can(P.RAB_WRITE) and not has_invoices and spk is None,
        can_void=issued and ctx.can(P.DOCUMENTS_ISSUE) and not has_invoices and spk is None,
        can_delete=q.status in DELETABLE and ctx.can(P.RAB_WRITE),
        can_invoice=issued and accepted and ctx.can(P.FINANCE_WRITE),
        spk=schemas.SpkBrief(id=spk.id, number=spk.number, status=spk.status) if spk else None,
        can_create_spk=issued and accepted and spk is None and ctx.can(P.PROJECTS_WRITE),
    )


@quotations_router.get(
    "", response_model=Page[schemas.QuotationListItem], summary="Daftar penawaran"
)
def list_quotations(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100),
    status_: DocStatus | None = Query(None, alias="status"),
    project_id: uuid.UUID | None = Query(None),
    rab_id: uuid.UUID | None = Query(None),
    client_response: ClientResponse | None = Query(None),
    sort: str | None = Query(None, description="created_at, number, grand_total; awali '-'"),
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.QuotationListItem]:
    items, total = quotations.list_quotations(
        db,
        ctx,
        params,
        q=q,
        status=status_,
        project_id=project_id,
        rab_id=rab_id,
        client_response=client_response,
        sort=sort,
    )
    return Page(
        items=[schemas.QuotationListItem(**_quotation_item(x)) for x in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@quotations_router.post(
    "",
    response_model=schemas.QuotationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat penawaran dari versi RAB yang disetujui",
)
def create_quotation(
    payload: schemas.QuotationCreate,
    ctx: RequestContext = Depends(require(P.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.QuotationOut:
    return _quotation_out(db, ctx, quotations.create(db, ctx, payload))


@quotations_router.get(
    "/{quotation_id}", response_model=schemas.QuotationOut, summary="Detail penawaran"
)
def get_quotation(
    quotation_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> schemas.QuotationOut:
    return _quotation_out(db, ctx, quotations.get(db, ctx, quotation_id))


@quotations_router.patch(
    "/{quotation_id}", response_model=schemas.QuotationOut, summary="Ubah penawaran (draft)"
)
def update_quotation(
    quotation_id: uuid.UUID,
    payload: schemas.QuotationUpdate,
    ctx: RequestContext = Depends(require(P.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.QuotationOut:
    return _quotation_out(db, ctx, quotations.update(db, ctx, quotation_id, payload))


@quotations_router.put(
    "/{quotation_id}/terms",
    response_model=schemas.QuotationOut,
    summary="Ganti jadwal pembayaran (termin); nilai dihitung server",
)
def put_terms(
    quotation_id: uuid.UUID,
    payload: schemas.TermsUpdate,
    ctx: RequestContext = Depends(require(P.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.QuotationOut:
    return _quotation_out(
        db, ctx, quotations.set_terms(db, ctx, quotation_id, payload.version, payload.terms)
    )


@quotations_router.post(
    "/{quotation_id}/transitions/{action}",
    response_model=schemas.QuotationOut,
    summary="submit / withdraw / approve / reject / reopen",
)
def quotation_transition(
    quotation_id: uuid.UUID,
    action: Action,
    payload: schemas.TransitionIn,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> schemas.QuotationOut:
    return _quotation_out(
        db, ctx, quotations.transition(db, ctx, quotation_id, action, payload.note)
    )


@quotations_router.get(
    "/{quotation_id}/preview.pdf",
    response_class=Response,
    summary="Pratinjau PDF",
    dependencies=EXPENSIVE,
)
def quotation_preview(
    quotation_id: uuid.UUID,
    download: bool = Query(False),
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
) -> Response:
    return file_response(quotations.preview_pdf(db, ctx, quotation_id), inline=not download)


@quotations_router.post(
    "/{quotation_id}/issue",
    dependencies=EXPENSIVE,
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Terbitkan penawaran (snapshot + PDF); idempoten dengan Idempotency-Key",
)
def issue_quotation(
    quotation_id: uuid.UUID,
    response: Response,
    idempotency_key: IdempotencyKey = None,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> DocumentOut:
    issued = quotations.issue(db, ctx, quotation_id, idempotency_key)
    if not issued.created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return DocumentOut.model_validate(issued.document)


@quotations_router.post(
    "/{quotation_id}/response",
    response_model=schemas.QuotationOut,
    summary="Catat tanggapan klien (diterima/ditolak)",
)
def quotation_response(
    quotation_id: uuid.UUID,
    payload: schemas.ResponseIn,
    ctx: RequestContext = Depends(require(P.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.QuotationOut:
    return _quotation_out(
        db, ctx, quotations.respond(db, ctx, quotation_id, payload.response, payload.note)
    )


@quotations_router.post(
    "/{quotation_id}/void", response_model=schemas.QuotationOut, summary="Batalkan penawaran terbit"
)
def void_quotation(
    quotation_id: uuid.UUID,
    payload: schemas.VoidIn,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> schemas.QuotationOut:
    return _quotation_out(db, ctx, quotations.void(db, ctx, quotation_id, payload.reason))


@quotations_router.delete(
    "/{quotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus penawaran draft/ditolak",
)
def delete_quotation(
    quotation_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> Response:
    quotations.delete(db, ctx, quotation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@quotations_router.post(
    "/{quotation_id}/terms/{term_id}/invoice",
    response_model=schemas.InvoiceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat invoice untuk satu termin",
)
def invoice_for_term(
    quotation_id: uuid.UUID,
    term_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.FINANCE_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.InvoiceOut:
    return _invoice_out(db, ctx, invoices.create_for_term(db, ctx, quotation_id, term_id))


# --------------------------------------------------------------------------- invoice mapping


def _invoice_item(inv: Invoice) -> dict[str, Any]:
    outstanding = (
        inv.grand_total - inv.amount_paid if inv.status is DocStatus.ISSUED else Decimal("0.00")
    )
    client = inv.client
    project = inv.project
    return {
        "id": inv.id,
        "number": inv.number,
        "kind": inv.kind,
        "status": inv.status,
        "title": inv.title,
        "project": schemas.Brief(id=project.id, number=project.number, name=project.name),
        "client": schemas.Brief(id=client.id, number=client.code, name=client.name),
        "quotation": schemas.RefBrief(id=inv.quotation_id, number=None)
        if inv.quotation_id
        else None,
        "issue_date": inv.issue_date,
        "due_date": inv.due_date,
        "currency": inv.currency,
        "grand_total": inv.grand_total,
        "amount_paid": inv.amount_paid,
        "outstanding": outstanding,
        "payment_state": payment_state(inv.status, inv.grand_total, inv.amount_paid),
        "overdue": is_overdue(
            inv.status, inv.due_date, inv.grand_total, inv.amount_paid, common.today()
        ),
        "created_at": inv.created_at,
    }


def _allocation_out(a: PaymentAllocation) -> schemas.AllocationOut:
    return schemas.AllocationOut(
        payment_id=a.payment_id,
        invoice_id=a.invoice_id,
        invoice_number=a.invoice.number,
        payment_date=a.payment.payment_date,
        method=a.payment.method,
        reference=a.payment.reference,
        amount=a.amount,
        payment_status=a.payment.status,
    )


def _invoice_out(db: Session, ctx: RequestContext, inv: Invoice) -> schemas.InvoiceOut:
    item = _invoice_item(inv)
    quotation = invoices.quotation_of(db, inv)
    if quotation is not None:
        item["quotation"] = schemas.RefBrief(id=quotation.id, number=quotation.number)
    term = inv.payment_term
    draft = inv.status is DocStatus.DRAFT
    issued = inv.status is DocStatus.ISSUED
    return schemas.InvoiceOut(
        **item,
        payment_term=schemas.TermRef(id=term.id, name=term.name, percent=term.percent)
        if term
        else None,
        tax_label=inv.tax_label,
        tax_rate_percent=inv.tax_rate_percent,
        subtotal=inv.subtotal,
        tax_amount=inv.tax_amount,
        notes=inv.notes,
        items=[schemas.InvoiceLineOut.model_validate(i) for i in inv.items],
        allocations=[_allocation_out(a) for a in payments.allocations_of_invoice(db, ctx, inv.id)],
        submitted_by=_user(inv.submitted_by),
        submitted_at=inv.submitted_at,
        decided_by=_user(inv.decided_by),
        decided_at=inv.decided_at,
        voided_at=inv.voided_at,
        void_reason=inv.void_reason,
        version=inv.version,
        approvals=_approvals(db, ctx, invoices.ENTITY, inv.id),
        allowed_actions=[
            a.value for a in allowed_actions(inv.status, ctx.permissions, write=P.FINANCE_WRITE)
        ],
        editable=draft and ctx.can(P.FINANCE_WRITE),
        lines_editable=draft and inv.kind is InvoiceKind.MANUAL and ctx.can(P.FINANCE_WRITE),
        can_issue=inv.status is DocStatus.APPROVED and ctx.can(P.DOCUMENTS_ISSUE),
        can_void=issued and inv.amount_paid == 0 and ctx.can(P.DOCUMENTS_ISSUE),
        can_delete=inv.status in DELETABLE and ctx.can(P.FINANCE_WRITE),
        can_record_payment=issued
        and inv.amount_paid < inv.grand_total
        and ctx.can(P.FINANCE_WRITE),
    )


@invoices_router.get("", response_model=Page[schemas.InvoiceListItem], summary="Daftar invoice")
def list_invoices(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100),
    status_: DocStatus | None = Query(None, alias="status"),
    payment_state_: PaymentState | None = Query(None, alias="payment_state"),
    overdue: bool | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    client_id: uuid.UUID | None = Query(None),
    quotation_id: uuid.UUID | None = Query(None),
    sort: str | None = Query(
        None, description="created_at, due_date, number, grand_total; awali '-'"
    ),
    ctx: RequestContext = Depends(require(P.FINANCE_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.InvoiceListItem]:
    items, total = invoices.list_invoices(
        db,
        ctx,
        params,
        q=q,
        status=status_,
        payment_state=payment_state_,
        overdue=overdue,
        project_id=project_id,
        client_id=client_id,
        quotation_id=quotation_id,
        sort=sort,
    )
    return Page(
        items=[schemas.InvoiceListItem(**_invoice_item(x)) for x in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@invoices_router.post(
    "",
    response_model=schemas.InvoiceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat invoice manual untuk proyek",
)
def create_invoice(
    payload: schemas.InvoiceCreate,
    ctx: RequestContext = Depends(require(P.FINANCE_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.InvoiceOut:
    return _invoice_out(db, ctx, invoices.create_manual(db, ctx, payload))


@invoices_router.get("/{invoice_id}", response_model=schemas.InvoiceOut, summary="Detail invoice")
def get_invoice(
    invoice_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.FINANCE_READ)),
    db: Session = Depends(get_db),
) -> schemas.InvoiceOut:
    return _invoice_out(db, ctx, invoices.get(db, ctx, invoice_id))


@invoices_router.patch(
    "/{invoice_id}", response_model=schemas.InvoiceOut, summary="Ubah invoice (draft)"
)
def update_invoice(
    invoice_id: uuid.UUID,
    payload: schemas.InvoiceUpdate,
    ctx: RequestContext = Depends(require(P.FINANCE_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.InvoiceOut:
    return _invoice_out(db, ctx, invoices.update(db, ctx, invoice_id, payload))


@invoices_router.post(
    "/{invoice_id}/transitions/{action}",
    response_model=schemas.InvoiceOut,
    summary="submit / withdraw / approve / reject / reopen",
)
def invoice_transition(
    invoice_id: uuid.UUID,
    action: Action,
    payload: schemas.TransitionIn,
    ctx: RequestContext = Depends(require(P.FINANCE_READ)),
    db: Session = Depends(get_db),
) -> schemas.InvoiceOut:
    return _invoice_out(db, ctx, invoices.transition(db, ctx, invoice_id, action, payload.note))


@invoices_router.get(
    "/{invoice_id}/preview.pdf",
    response_class=Response,
    summary="Pratinjau PDF",
    dependencies=EXPENSIVE,
)
def invoice_preview(
    invoice_id: uuid.UUID,
    download: bool = Query(False),
    ctx: RequestContext = Depends(require(P.FINANCE_READ)),
    db: Session = Depends(get_db),
) -> Response:
    return file_response(invoices.preview_pdf(db, ctx, invoice_id), inline=not download)


@invoices_router.post(
    "/{invoice_id}/issue",
    dependencies=EXPENSIVE,
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Terbitkan invoice (nomor, snapshot, PDF); idempoten dengan Idempotency-Key",
)
def issue_invoice(
    invoice_id: uuid.UUID,
    response: Response,
    idempotency_key: IdempotencyKey = None,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> DocumentOut:
    issued = invoices.issue(db, ctx, invoice_id, idempotency_key)
    if not issued.created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return DocumentOut.model_validate(issued.document)


@invoices_router.post(
    "/{invoice_id}/void", response_model=schemas.InvoiceOut, summary="Batalkan invoice terbit"
)
def void_invoice(
    invoice_id: uuid.UUID,
    payload: schemas.VoidIn,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> schemas.InvoiceOut:
    return _invoice_out(db, ctx, invoices.void(db, ctx, invoice_id, payload.reason))


@invoices_router.delete(
    "/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Hapus invoice draft/ditolak"
)
def delete_invoice(
    invoice_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.FINANCE_WRITE)),
    db: Session = Depends(get_db),
) -> Response:
    invoices.delete(db, ctx, invoice_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- payments


def _payment_out(p: Payment) -> schemas.PaymentOut:
    allocated = payments.allocated(p)
    client = p.client
    return schemas.PaymentOut(
        id=p.id,
        client=schemas.Brief(id=client.id, number=client.code, name=client.name),
        payment_date=p.payment_date,
        amount=p.amount,
        currency=p.currency,
        method=p.method,
        reference=p.reference,
        notes=p.notes,
        status=p.status,
        allocated=allocated,
        unallocated=p.amount - allocated if p.status is PaymentStatus.RECORDED else Decimal("0.00"),
        allocations=[_allocation_out(a) for a in p.allocations],
        recorded_by=_user(p.recorded_by),
        created_at=p.created_at,
        voided_at=p.voided_at,
        voided_by=_user(p.voided_by),
        void_reason=p.void_reason,
    )


@payments_router.get("", response_model=Page[schemas.PaymentOut], summary="Daftar pembayaran")
def list_payments(
    params: PageParams = Depends(page_params),
    client_id: uuid.UUID | None = Query(None),
    invoice_id: uuid.UUID | None = Query(None),
    status_: PaymentStatus | None = Query(None, alias="status"),
    sort: str | None = Query(None, description="payment_date, amount, created_at; awali '-'"),
    ctx: RequestContext = Depends(require(P.FINANCE_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.PaymentOut]:
    items, total = payments.list_payments(
        db, ctx, params, client_id=client_id, invoice_id=invoice_id, status=status_, sort=sort
    )
    return Page(
        items=[_payment_out(p) for p in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@payments_router.post(
    "",
    response_model=schemas.PaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Catat pembayaran (+ alokasi ke invoice); idempoten dengan Idempotency-Key",
)
def record_payment(
    payload: schemas.PaymentCreate,
    response: Response,
    idempotency_key: IdempotencyKey = None,
    ctx: RequestContext = Depends(require(P.FINANCE_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.PaymentOut:
    payment, created = payments.record(db, ctx, payload, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return _payment_out(payment)


@payments_router.get(
    "/{payment_id}", response_model=schemas.PaymentOut, summary="Detail pembayaran"
)
def get_payment(
    payment_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.FINANCE_READ)),
    db: Session = Depends(get_db),
) -> schemas.PaymentOut:
    return _payment_out(payments.get(db, ctx, payment_id))


@payments_router.post(
    "/{payment_id}/allocations",
    response_model=schemas.PaymentOut,
    summary="Alokasikan sisa pembayaran ke invoice",
)
def allocate_payment(
    payment_id: uuid.UUID,
    payload: schemas.AllocateIn,
    ctx: RequestContext = Depends(require(P.FINANCE_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.PaymentOut:
    return _payment_out(
        payments.allocate(
            db,
            ctx,
            payment_id,
            schemas.AllocationIn(invoice_id=payload.invoice_id, amount=payload.amount),
        )
    )


@payments_router.post(
    "/{payment_id}/void", response_model=schemas.PaymentOut, summary="Batalkan pembayaran"
)
def void_payment(
    payment_id: uuid.UUID,
    payload: schemas.VoidIn,
    ctx: RequestContext = Depends(require(P.FINANCE_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.PaymentOut:
    return _payment_out(payments.void(db, ctx, payment_id, payload.reason))
