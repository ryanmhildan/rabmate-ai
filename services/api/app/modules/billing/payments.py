"""Recorded payments and their allocation to issued invoices (ADR-036).

- A payment is money a user with finance.write recorded (method, reference, date). Invoices are
  "paid" only through these records — never because someone or something claims so.
- Allocations go to issued invoices of the same client and currency, never above what is still
  outstanding; a payment can be split across invoices and part of it may stay unallocated.
- Invoices are locked in id order (no deadlocks between concurrent payments) and
  `invoices.amount_paid` is updated in the same transaction (a CHECK keeps it ≤ grand total).
- Payments are never deleted or edited: a mistake is voided with a reason, which releases its
  allocations. Recording accepts an Idempotency-Key so a retried request cannot pay twice.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import AppError, BusinessValidationError, ConflictError, NotFoundError
from app.core.pagination import PageParams, apply_sort, paginate
from app.modules.billing import common
from app.modules.billing.models import (
    DocStatus,
    Invoice,
    Payment,
    PaymentAllocation,
    PaymentStatus,
)
from app.modules.billing.schemas import AllocationIn, PaymentCreate
from app.modules.clients.models import Client
from app.modules.documents import formatting as fmt

ENTITY = "payment"
SORT = {
    "payment_date": Payment.payment_date,
    "amount": Payment.amount,
    "created_at": Payment.created_at,
}
ZERO = Decimal("0.00")


class PaymentKeyReusedError(AppError):
    status_code = 422
    code = "idempotency_key_reused"
    message = "Idempotency-Key ini sudah dipakai untuk pembayaran lain."


def get(db: Session, ctx: RequestContext, payment_id: uuid.UUID, *, lock: bool = False) -> Payment:
    stmt = (
        select(Payment)
        .where(Payment.id == payment_id, Payment.organization_id == ctx.organization_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=Payment)
    payment = db.execute(stmt).unique().scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Pembayaran tidak ditemukan.")
    return payment


def allocated(payment: Payment) -> Decimal:
    return sum((a.amount for a in payment.allocations), ZERO)


def list_payments(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    client_id: uuid.UUID | None,
    invoice_id: uuid.UUID | None,
    status: PaymentStatus | None,
    sort: str | None,
) -> tuple[list[Payment], int]:
    stmt = select(Payment).where(Payment.organization_id == ctx.organization_id)
    if client_id:
        stmt = stmt.where(Payment.client_id == client_id)
    if invoice_id:
        stmt = stmt.where(
            Payment.id.in_(
                select(PaymentAllocation.payment_id).where(
                    PaymentAllocation.invoice_id == invoice_id,
                    PaymentAllocation.organization_id == ctx.organization_id,
                )
            )
        )
    if status:
        stmt = stmt.where(Payment.status == status)
    return paginate(db, apply_sort(stmt, sort, SORT, default="-payment_date"), params)


def allocations_of_invoice(
    db: Session, ctx: RequestContext, invoice_id: uuid.UUID
) -> list[PaymentAllocation]:
    return list(
        db.execute(
            select(PaymentAllocation)
            .where(
                PaymentAllocation.invoice_id == invoice_id,
                PaymentAllocation.organization_id == ctx.organization_id,
            )
            .order_by(PaymentAllocation.created_at)
        )
        .unique()
        .scalars()
    )


def _lock_invoices(
    db: Session, ctx: RequestContext, ids: list[uuid.UUID]
) -> dict[uuid.UUID, Invoice]:
    found = (
        db.execute(
            select(Invoice)
            .where(Invoice.id.in_(ids), Invoice.organization_id == ctx.organization_id)
            .order_by(Invoice.id)
            .with_for_update(of=Invoice)
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalars()
        .all()
    )
    invoices = {invoice.id: invoice for invoice in found}
    missing = [str(i) for i in ids if i not in invoices]
    if missing:
        raise NotFoundError("Invoice tidak ditemukan.", details={"invoice_ids": missing})
    return invoices


def _apply_allocations(
    db: Session,
    ctx: RequestContext,
    payment: Payment,
    allocations: list[AllocationIn],
    *,
    available: Decimal,
) -> None:
    if not allocations:
        return
    ids = [a.invoice_id for a in allocations]
    if len(set(ids)) != len(ids):
        raise BusinessValidationError("Satu invoice hanya boleh muncul sekali per pembayaran.")
    if sum((a.amount for a in allocations), ZERO) > available:
        raise BusinessValidationError("Jumlah alokasi melebihi nilai pembayaran yang tersedia.")
    invoices = _lock_invoices(db, ctx, ids)
    existing = {a.invoice_id: a for a in payment.allocations}
    for index, item in enumerate(allocations):
        invoice = invoices[item.invoice_id]
        loc = {"loc": ["body", "allocations", index, "amount"]}
        if invoice.status is not DocStatus.ISSUED:
            raise BusinessValidationError(
                "Pembayaran hanya dapat dialokasikan ke invoice yang sudah terbit.",
                details=[{**loc, "msg": "Invoice belum terbit atau dibatalkan."}],
            )
        if invoice.client_id != payment.client_id:
            raise BusinessValidationError(
                "Invoice milik klien lain.", details=[{**loc, "msg": "Klien berbeda."}]
            )
        if invoice.currency != payment.currency:
            raise BusinessValidationError(
                "Mata uang invoice berbeda dengan pembayaran.",
                details=[{**loc, "msg": "Mata uang berbeda."}],
            )
        outstanding = invoice.grand_total - invoice.amount_paid
        if item.amount > outstanding:
            remaining = fmt.money(outstanding, invoice.currency)
            raise BusinessValidationError(
                f"Alokasi melebihi sisa tagihan {invoice.number} ({remaining}).",
                details=[{**loc, "msg": f"Sisa tagihan {remaining}."}],
            )
        current = existing.get(invoice.id)
        if current is not None:
            current.amount += item.amount
        else:
            payment.allocations.append(
                PaymentAllocation(
                    organization_id=ctx.organization_id,
                    invoice_id=invoice.id,
                    amount=item.amount,
                )
            )
        invoice.amount_paid += item.amount


def record(
    db: Session, ctx: RequestContext, payload: PaymentCreate, idempotency_key: str | None
) -> tuple[Payment, bool]:
    if idempotency_key:
        existing = (
            db.execute(
                select(Payment).where(
                    Payment.organization_id == ctx.organization_id,
                    Payment.idempotency_key == idempotency_key,
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        if existing is not None:
            if (existing.client_id, existing.amount) != (payload.client_id, payload.amount):
                raise PaymentKeyReusedError(details={"payment_id": str(existing.id)})
            return existing, False
    client = db.execute(
        select(Client).where(
            Client.id == payload.client_id, Client.organization_id == ctx.organization_id
        )
    ).scalar_one_or_none()
    if client is None:
        raise NotFoundError("Klien tidak ditemukan.")
    if payload.payment_date > common.today():
        raise BusinessValidationError(
            "Tanggal pembayaran tidak boleh di masa depan.",
            details=[{"loc": ["body", "payment_date"], "msg": "Tidak boleh di masa depan."}],
        )
    payment = Payment(
        organization_id=ctx.organization_id,
        client_id=client.id,
        payment_date=payload.payment_date,
        amount=payload.amount,
        currency=payload.currency,
        method=payload.method,
        reference=payload.reference,
        notes=payload.notes,
        status=PaymentStatus.RECORDED,
        idempotency_key=idempotency_key,
        recorded_by_id=ctx.user_id,
    )
    db.add(payment)
    try:
        db.flush()
    except IntegrityError:  # same key raced in from a concurrent retry
        db.rollback()
        if idempotency_key:
            replay = (
                db.execute(
                    select(Payment).where(
                        Payment.organization_id == ctx.organization_id,
                        Payment.idempotency_key == idempotency_key,
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
            if replay is not None:
                return replay, False
        raise
    _apply_allocations(db, ctx, payment, payload.allocations, available=payload.amount)
    db.flush()
    common.record_audit(
        db,
        ctx,
        "payment.record",
        ENTITY,
        payment.id,
        f"{client.name}: {payment.currency} {payment.amount}",
        {
            "amount": {"from": None, "to": payment.amount},
            "allocations": {
                "from": None,
                "to": [f"{a.invoice_id}: {a.amount}" for a in payload.allocations] or None,
            },
        },
    )
    db.commit()
    return get(db, ctx, payment.id), True


def allocate(
    db: Session, ctx: RequestContext, payment_id: uuid.UUID, item: AllocationIn
) -> Payment:
    payment = get(db, ctx, payment_id, lock=True)
    if payment.status is not PaymentStatus.RECORDED:
        raise ConflictError("Pembayaran yang dibatalkan tidak dapat dialokasikan.")
    _apply_allocations(db, ctx, payment, [item], available=payment.amount - allocated(payment))
    db.flush()
    common.record_audit(
        db,
        ctx,
        "payment.allocate",
        ENTITY,
        payment.id,
        f"{payment.currency} {item.amount}",
        {"allocation": {"from": None, "to": f"{item.invoice_id}: {item.amount}"}},
    )
    db.commit()
    return get(db, ctx, payment_id)


def void(db: Session, ctx: RequestContext, payment_id: uuid.UUID, reason: str) -> Payment:
    payment = get(db, ctx, payment_id, lock=True)
    if payment.status is PaymentStatus.VOID:
        raise ConflictError("Pembayaran sudah dibatalkan.")
    ids = [a.invoice_id for a in payment.allocations]
    invoices = _lock_invoices(db, ctx, ids) if ids else {}
    for allocation in payment.allocations:
        invoices[allocation.invoice_id].amount_paid -= allocation.amount
    payment.status = PaymentStatus.VOID
    payment.voided_at = common.now()
    payment.voided_by_id = ctx.user_id
    payment.void_reason = reason
    db.flush()
    common.record_audit(
        db,
        ctx,
        "payment.void",
        ENTITY,
        payment.id,
        f"{payment.currency} {payment.amount}",
        {"status": {"from": "recorded", "to": "void"}, "void_reason": {"from": None, "to": reason}},
    )
    db.commit()
    return get(db, ctx, payment_id)
