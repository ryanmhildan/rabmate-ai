from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.modules.audit.router import AuditLogOut, recent_entries
from app.modules.billing.common import today
from app.modules.billing.models import (
    ClientResponse,
    DocStatus,
    Invoice,
    Payment,
    PaymentStatus,
    PaymentTerm,
    Quotation,
)
from app.modules.clients.models import Client
from app.modules.documents.models import DocumentStatus, IssuedDocument
from app.modules.identity.permissions import Permission
from app.modules.projects.models import Project, ProjectStatus
from app.modules.rab.models import RabStatus, RabVersion
from app.modules.workorders.models import Bast, BastKind, Spk

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

RECENT_ACTIVITY_LIMIT = 10


class BudgetByCurrency(BaseModel):
    currency: str
    total: Decimal
    projects: int


class AmountByCurrency(BaseModel):
    currency: str
    total: Decimal
    count: int


class RabSummary(BaseModel):
    draft: int
    in_review: int
    approved: int
    # Sum of currently approved versions (one per RAB), per currency.
    approved_total: list[AmountByCurrency]


class DocumentSummary(BaseModel):
    issued: int
    void: int
    # Approved RAB versions without a valid issued document yet (ready to issue).
    approved_rab_not_issued: int


class QuotationSummary(BaseModel):
    draft: int
    in_review: int
    # Issued and still waiting for the client's answer.
    awaiting_response: int
    accepted: int


class BillingSummary(BaseModel):
    # Issued invoices: total minus recorded payments, per currency.
    outstanding: list[AmountByCurrency]
    overdue: list[AmountByCurrency]
    received_this_month: list[AmountByCurrency]
    # Terms of accepted quotations due within 30 days that have no invoice yet.
    terms_due_soon: int


class WorkOrderSummary(BaseModel):
    # Issued quotations the client accepted that have no SPK yet.
    accepted_without_spk: int
    spk_in_review: int
    # Issued SPKs without an issued final BAST (work still to be handed over).
    spk_open: int
    bast_in_review: int


class DashboardSummary(BaseModel):
    projects_total: int
    projects_by_status: dict[ProjectStatus, int]
    clients_active: int
    # Sum of project budgets for prospect/active/on-hold projects, per currency (never mixed).
    open_budget: list[BudgetByCurrency]
    # None when the caller lacks the permission (distinct from "nothing yet").
    rab: RabSummary | None
    documents: DocumentSummary | None
    quotations: QuotationSummary | None
    billing: BillingSummary | None
    workorders: WorkOrderSummary
    recent_activity: list[AuditLogOut] | None


OPEN_STATUSES = (ProjectStatus.PROSPECT, ProjectStatus.ACTIVE, ProjectStatus.ON_HOLD)


@router.get("/summary", response_model=DashboardSummary, summary="Ringkasan dashboard")
def summary(
    ctx: RequestContext = Depends(require(Permission.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> DashboardSummary:
    org_id = ctx.organization_id
    by_status = dict(
        db.execute(
            select(Project.status, func.count())
            .where(Project.organization_id == org_id)
            .group_by(Project.status)
        ).all()
    )
    budgets = db.execute(
        select(Project.currency, func.sum(Project.budget_amount), func.count())
        .where(
            Project.organization_id == org_id,
            Project.status.in_(OPEN_STATUSES),
            Project.budget_amount.is_not(None),
        )
        .group_by(Project.currency)
        .order_by(Project.currency)
    ).all()
    clients_active = 0
    if ctx.can(Permission.CLIENTS_READ):
        clients_active = db.execute(
            select(func.count())
            .select_from(Client)
            .where(Client.organization_id == org_id, Client.is_active.is_(True))
        ).scalar_one()

    rab: RabSummary | None = None
    if ctx.can(Permission.RAB_READ):
        counts = dict(
            db.execute(
                select(RabVersion.status, func.count())
                .where(
                    RabVersion.organization_id == org_id,
                    RabVersion.status.in_(
                        (RabStatus.DRAFT, RabStatus.IN_REVIEW, RabStatus.APPROVED)
                    ),
                )
                .group_by(RabVersion.status)
            ).all()
        )
        approved_totals = db.execute(
            select(RabVersion.currency, func.sum(RabVersion.grand_total), func.count())
            .where(RabVersion.organization_id == org_id, RabVersion.status == RabStatus.APPROVED)
            .group_by(RabVersion.currency)
            .order_by(RabVersion.currency)
        ).all()
        rab = RabSummary(
            draft=counts.get(RabStatus.DRAFT, 0),
            in_review=counts.get(RabStatus.IN_REVIEW, 0),
            approved=counts.get(RabStatus.APPROVED, 0),
            approved_total=[
                AmountByCurrency(currency=c, total=t, count=n) for c, t, n in approved_totals
            ],
        )

    documents: DocumentSummary | None = None
    if ctx.can(Permission.DOCUMENTS_READ) and ctx.can(Permission.RAB_READ):
        doc_counts = dict(
            db.execute(
                select(IssuedDocument.status, func.count())
                .where(IssuedDocument.organization_id == org_id)
                .group_by(IssuedDocument.status)
            ).all()
        )
        issued_versions = select(IssuedDocument.rab_version_id).where(
            IssuedDocument.organization_id == org_id,
            IssuedDocument.status == DocumentStatus.ISSUED,
            IssuedDocument.rab_version_id.is_not(None),
        )
        waiting = db.execute(
            select(func.count())
            .select_from(RabVersion)
            .where(
                RabVersion.organization_id == org_id,
                RabVersion.status == RabStatus.APPROVED,
                RabVersion.id.not_in(issued_versions),
            )
        ).scalar_one()
        documents = DocumentSummary(
            issued=doc_counts.get(DocumentStatus.ISSUED, 0),
            void=doc_counts.get(DocumentStatus.VOID, 0),
            approved_rab_not_issued=waiting,
        )

    quotation_summary: QuotationSummary | None = None
    if ctx.can(Permission.RAB_READ):
        q_counts = dict(
            db.execute(
                select(Quotation.status, func.count())
                .where(Quotation.organization_id == org_id)
                .group_by(Quotation.status)
            ).all()
        )
        responses = dict(
            db.execute(
                select(Quotation.client_response, func.count())
                .where(Quotation.organization_id == org_id, Quotation.status == DocStatus.ISSUED)
                .group_by(Quotation.client_response)
            ).all()
        )
        quotation_summary = QuotationSummary(
            draft=q_counts.get(DocStatus.DRAFT, 0),
            in_review=q_counts.get(DocStatus.IN_REVIEW, 0),
            awaiting_response=responses.get(None, 0),
            accepted=responses.get(ClientResponse.ACCEPTED, 0),
        )

    billing: BillingSummary | None = None
    if ctx.can(Permission.FINANCE_READ):
        business_today = today()
        open_invoice = (
            Invoice.organization_id == org_id,
            Invoice.status == DocStatus.ISSUED,
            Invoice.amount_paid < Invoice.grand_total,
        )
        remaining = func.sum(Invoice.grand_total - Invoice.amount_paid)
        outstanding = db.execute(
            select(Invoice.currency, remaining, func.count())
            .where(*open_invoice)
            .group_by(Invoice.currency)
            .order_by(Invoice.currency)
        ).all()
        overdue = db.execute(
            select(Invoice.currency, remaining, func.count())
            .where(*open_invoice, Invoice.due_date < business_today)
            .group_by(Invoice.currency)
            .order_by(Invoice.currency)
        ).all()
        received = db.execute(
            select(Payment.currency, func.sum(Payment.amount), func.count())
            .where(
                Payment.organization_id == org_id,
                Payment.status == PaymentStatus.RECORDED,
                Payment.payment_date >= business_today.replace(day=1),
            )
            .group_by(Payment.currency)
            .order_by(Payment.currency)
        ).all()
        invoiced_terms = select(Invoice.payment_term_id).where(
            Invoice.organization_id == org_id,
            Invoice.status != DocStatus.VOID,
            Invoice.payment_term_id.is_not(None),
        )
        terms_due = db.execute(
            select(func.count())
            .select_from(PaymentTerm)
            .join(Quotation, Quotation.id == PaymentTerm.quotation_id)
            .where(
                PaymentTerm.organization_id == org_id,
                Quotation.status == DocStatus.ISSUED,
                Quotation.client_response == ClientResponse.ACCEPTED,
                PaymentTerm.due_date.is_not(None),
                PaymentTerm.due_date <= business_today + timedelta(days=30),
                PaymentTerm.id.not_in(invoiced_terms),
            )
        ).scalar_one()

        def amounts(rows: Sequence[Row[str, Decimal, int]]) -> list[AmountByCurrency]:
            return [AmountByCurrency(currency=c, total=t, count=n) for c, t, n in rows]

        billing = BillingSummary(
            outstanding=amounts(outstanding),
            overdue=amounts(overdue),
            received_this_month=amounts(received),
            terms_due_soon=terms_due,
        )

    spk_counts = dict(
        db.execute(
            select(Spk.status, func.count())
            .where(Spk.organization_id == org_id)
            .group_by(Spk.status)
        ).all()
    )
    with_spk = select(Spk.quotation_id).where(
        Spk.organization_id == org_id, Spk.status != DocStatus.VOID
    )
    finished = select(Bast.spk_id).where(
        Bast.organization_id == org_id,
        Bast.kind == BastKind.FINAL,
        Bast.status == DocStatus.ISSUED,
    )
    workorders = WorkOrderSummary(
        accepted_without_spk=db.execute(
            select(func.count()).where(
                Quotation.organization_id == org_id,
                Quotation.status == DocStatus.ISSUED,
                Quotation.client_response == ClientResponse.ACCEPTED,
                Quotation.id.not_in(with_spk),
            )
        ).scalar_one(),
        spk_in_review=spk_counts.get(DocStatus.IN_REVIEW, 0),
        spk_open=db.execute(
            select(func.count()).where(
                Spk.organization_id == org_id,
                Spk.status == DocStatus.ISSUED,
                Spk.id.not_in(finished),
            )
        ).scalar_one(),
        bast_in_review=db.execute(
            select(func.count()).where(
                Bast.organization_id == org_id, Bast.status == DocStatus.IN_REVIEW
            )
        ).scalar_one(),
    )

    return DashboardSummary(
        rab=rab,
        workorders=workorders,
        quotations=quotation_summary,
        billing=billing,
        documents=documents,
        projects_total=sum(by_status.values()),
        projects_by_status={status: by_status.get(status, 0) for status in ProjectStatus},
        clients_active=clients_active,
        open_budget=[
            BudgetByCurrency(currency=currency, total=total, projects=count)
            for currency, total, count in budgets
        ],
        recent_activity=(
            recent_entries(db, org_id, RECENT_ACTIVITY_LIMIT)
            if ctx.can(Permission.AUDIT_READ)
            else None
        ),
    )
