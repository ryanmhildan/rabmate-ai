"""Quotations, payment schedules (termin), invoices, payments and their allocations.

Money columns are NUMERIC(20,2); every amount shown on a quotation or term invoice comes from the
frozen RAB values and the deterministic allocation in billing/terms.py. Payment status is derived
from recorded payments only (`invoices.amount_paid` is maintained under row locks).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.clients.models import Client
from app.modules.identity.models import User
from app.modules.projects.models import Project
from app.modules.rab.models import RabVersion


class DocStatus(StrEnum):
    """Workflow shared by quotations and invoices (see billing/workflow.py)."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ISSUED = "issued"
    VOID = "void"


class ClientResponse(StrEnum):
    ACCEPTED = "accepted"
    DECLINED = "declined"


class TermBasis(StrEnum):
    PERCENT = "percent"
    AMOUNT = "amount"


class InvoiceKind(StrEnum):
    TERM = "term"  # one payment term of an accepted quotation; amounts copied from the schedule
    MANUAL = "manual"  # free lines; totals from the calculation module


class PaymentMethod(StrEnum):
    TRANSFER = "transfer"
    CASH = "cash"
    CHEQUE = "cheque"
    GIRO = "giro"
    OTHER = "other"


class PaymentStatus(StrEnum):
    RECORDED = "recorded"
    VOID = "void"


class WorkflowColumns:
    """Review/approval bookkeeping common to quotations, invoices, SPK and BAST."""

    if TYPE_CHECKING:
        # Declared by each subclass (with its own enum CHECK name); typed here so the shared
        # workflow code (billing/common.apply_transition) can accept any workflowed document.
        id: Mapped[uuid.UUID]
        status: Mapped[DocStatus]

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Quotation(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowColumns, Base):
    """A price offer to the client based on one approved RAB version (values copied, frozen)."""

    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "id", name="uq_quotations_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_quotations_project_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "rab_version_id"],
            ["rab_versions.organization_id", "rab_versions.id"],
            name="fk_quotations_rab_version_same_org",
        ),
        Index("ix_quotations_organization_id_created_at", "organization_id", "created_at"),
        CheckConstraint(
            "grand_total >= 0 AND taxable_base >= 0 AND tax_amount >= 0", name="amounts_valid"
        ),
        CheckConstraint("grand_total = taxable_base + tax_amount", name="total_consistent"),
        CheckConstraint(
            "(client_response IS NULL) = (responded_at IS NULL)", name="response_timestamped"
        ),
        CheckConstraint("(status = 'void') = (voided_at IS NOT NULL)", name="void_timestamped"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    number: Mapped[str] = mapped_column(String(32))
    project_id: Mapped[uuid.UUID] = mapped_column()
    rab_version_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[DocStatus] = mapped_column(str_enum(DocStatus, "quotation_status"))
    subject: Mapped[str] = mapped_column(String(300))
    valid_until: Mapped[date | None] = mapped_column(Date)
    introduction: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # Copied from the approved RAB version when the quotation is created.
    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    taxable_base: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    tax_label: Mapped[str | None] = mapped_column(String(32))
    tax_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    client_response: Mapped[ClientResponse | None] = mapped_column(
        str_enum(ClientResponse, "client_response")
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    project: Mapped[Project] = relationship(
        primaryjoin="and_(Quotation.project_id == Project.id, "
        "Quotation.organization_id == Project.organization_id)",
        foreign_keys="[Quotation.project_id, Quotation.organization_id]",
        viewonly=True,
        lazy="joined",
    )
    rab_version: Mapped[RabVersion] = relationship(
        primaryjoin="Quotation.rab_version_id == RabVersion.id",
        foreign_keys="[Quotation.rab_version_id]",
        viewonly=True,
        lazy="joined",
    )
    payment_terms: Mapped[list[PaymentTerm]] = relationship(
        back_populates="quotation",
        primaryjoin="Quotation.id == PaymentTerm.quotation_id",
        foreign_keys="[PaymentTerm.quotation_id]",
        order_by="PaymentTerm.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    submitted_by: Mapped[User | None] = relationship(
        foreign_keys="Quotation.submitted_by_id", lazy="joined"
    )
    decided_by: Mapped[User | None] = relationship(
        foreign_keys="Quotation.decided_by_id", lazy="joined"
    )


class PaymentTerm(UUIDPrimaryKeyMixin, Base):
    """One instalment (termin) of a quotation. Amounts are computed by billing/terms.py."""

    __tablename__ = "payment_terms"
    __table_args__ = (
        UniqueConstraint("quotation_id", "position"),
        UniqueConstraint("organization_id", "id", name="uq_payment_terms_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "quotation_id"],
            ["quotations.organization_id", "quotations.id"],
            name="fk_payment_terms_quotation_same_org",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(basis = 'percent') = (percent IS NOT NULL)", name="percent_matches_basis"
        ),
        CheckConstraint(
            "percent IS NULL OR (percent > 0 AND percent <= 100)", name="percent_range"
        ),
        CheckConstraint("amount >= 0 AND tax_amount >= 0", name="amounts_non_negative"),
        CheckConstraint("total_amount = amount + tax_amount", name="total_consistent"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    quotation_id: Mapped[uuid.UUID] = mapped_column()
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    basis: Mapped[TermBasis] = mapped_column(str_enum(TermBasis, "term_basis"))
    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))  # before tax (DPP share)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    due_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(500))

    quotation: Mapped[Quotation] = relationship(
        back_populates="payment_terms",
        primaryjoin="PaymentTerm.quotation_id == Quotation.id",
        foreign_keys=[quotation_id],
    )


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowColumns, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "id", name="uq_invoices_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_invoices_project_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_invoices_client_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "quotation_id"],
            ["quotations.organization_id", "quotations.id"],
            name="fk_invoices_quotation_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "payment_term_id"],
            ["payment_terms.organization_id", "payment_terms.id"],
            name="fk_invoices_payment_term_same_org",
        ),
        # A payment term is billed by at most one invoice that is not void.
        Index(
            "uq_invoices_one_per_payment_term",
            "payment_term_id",
            unique=True,
            postgresql_where=text("status <> 'void'"),
        ),
        Index("ix_invoices_organization_id_due_date", "organization_id", "due_date"),
        CheckConstraint(
            "(kind = 'term') = (payment_term_id IS NOT NULL)", name="term_invoice_has_term"
        ),
        CheckConstraint(
            "subtotal >= 0 AND tax_amount >= 0 AND grand_total = subtotal + tax_amount",
            name="totals_consistent",
        ),
        CheckConstraint(
            "amount_paid >= 0 AND amount_paid <= grand_total", name="paid_within_total"
        ),
        # Only issued invoices are voided, so both states carry the number and dates.
        CheckConstraint(
            "status NOT IN ('issued', 'void')"
            " OR (number IS NOT NULL AND issue_date IS NOT NULL AND due_date IS NOT NULL)",
            name="issued_has_number_and_dates",
        ),
        CheckConstraint(
            "due_date IS NULL OR issue_date IS NULL OR due_date >= issue_date",
            name="due_after_issue",
        ),
        CheckConstraint("(status = 'void') = (voided_at IS NOT NULL)", name="void_timestamped"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    number: Mapped[str | None] = mapped_column(String(32))  # assigned at issuance
    kind: Mapped[InvoiceKind] = mapped_column(str_enum(InvoiceKind, "invoice_kind"))
    status: Mapped[DocStatus] = mapped_column(str_enum(DocStatus, "invoice_status"))
    project_id: Mapped[uuid.UUID] = mapped_column()
    client_id: Mapped[uuid.UUID] = mapped_column()
    quotation_id: Mapped[uuid.UUID | None] = mapped_column()
    payment_term_id: Mapped[uuid.UUID | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(300))
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    tax_label: Mapped[str | None] = mapped_column(String(32))
    tax_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=Decimal("0"), server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice",
        primaryjoin="Invoice.id == InvoiceItem.invoice_id",
        foreign_keys="[InvoiceItem.invoice_id]",
        order_by="InvoiceItem.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    project: Mapped[Project] = relationship(
        primaryjoin="and_(Invoice.project_id == Project.id, "
        "Invoice.organization_id == Project.organization_id)",
        foreign_keys="[Invoice.project_id, Invoice.organization_id]",
        viewonly=True,
        lazy="joined",
    )
    client: Mapped[Client] = relationship(
        primaryjoin="and_(Invoice.client_id == Client.id, "
        "Invoice.organization_id == Client.organization_id)",
        foreign_keys="[Invoice.client_id, Invoice.organization_id]",
        viewonly=True,
        lazy="joined",
    )
    payment_term: Mapped[PaymentTerm | None] = relationship(
        primaryjoin="and_(Invoice.payment_term_id == PaymentTerm.id, "
        "Invoice.organization_id == PaymentTerm.organization_id)",
        foreign_keys="[Invoice.payment_term_id, Invoice.organization_id]",
        viewonly=True,
        lazy="joined",
    )
    submitted_by: Mapped[User | None] = relationship(
        foreign_keys="Invoice.submitted_by_id", lazy="joined"
    )
    decided_by: Mapped[User | None] = relationship(
        foreign_keys="Invoice.decided_by_id", lazy="joined"
    )


class InvoiceItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        UniqueConstraint("invoice_id", "position"),
        ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_invoice_items_invoice_same_org",
            ondelete="CASCADE",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0 AND amount >= 0", name="amounts_non_negative"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    invoice_id: Mapped[uuid.UUID] = mapped_column()
    position: Mapped[int]
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))

    invoice: Mapped[Invoice] = relationship(
        back_populates="items",
        primaryjoin="InvoiceItem.invoice_id == Invoice.id",
        foreign_keys=[invoice_id],
    )


class Payment(UUIDPrimaryKeyMixin, Base):
    """Money received from a client. Append-only; corrected by voiding with a reason."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_payments_organization_id_id"),
        UniqueConstraint("organization_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_payments_client_same_org",
        ),
        Index("ix_payments_organization_id_payment_date", "organization_id", "payment_date"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("(status = 'void') = (voided_at IS NOT NULL)", name="void_timestamped"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    client_id: Mapped[uuid.UUID] = mapped_column()
    payment_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3))
    method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod, "payment_method"))
    reference: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PaymentStatus] = mapped_column(str_enum(PaymentStatus, "payment_status"))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)

    allocations: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="payment",
        primaryjoin="Payment.id == PaymentAllocation.payment_id",
        foreign_keys="[PaymentAllocation.payment_id]",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    client: Mapped[Client] = relationship(
        primaryjoin="and_(Payment.client_id == Client.id, "
        "Payment.organization_id == Client.organization_id)",
        foreign_keys="[Payment.client_id, Payment.organization_id]",
        viewonly=True,
        lazy="joined",
    )
    recorded_by: Mapped[User | None] = relationship(foreign_keys=[recorded_by_id], lazy="joined")
    voided_by: Mapped[User | None] = relationship(foreign_keys=[voided_by_id], lazy="joined")


class PaymentAllocation(UUIDPrimaryKeyMixin, Base):
    """Part of a payment applied to one invoice."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("payment_id", "invoice_id"),
        ForeignKeyConstraint(
            ["organization_id", "payment_id"],
            ["payments.organization_id", "payments.id"],
            name="fk_payment_allocations_payment_same_org",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_payment_allocations_invoice_same_org",
        ),
        Index("ix_payment_allocations_invoice_id", "invoice_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    payment_id: Mapped[uuid.UUID] = mapped_column()
    invoice_id: Mapped[uuid.UUID] = mapped_column()
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    payment: Mapped[Payment] = relationship(
        back_populates="allocations",
        primaryjoin="PaymentAllocation.payment_id == Payment.id",
        foreign_keys=[payment_id],
    )
    invoice: Mapped[Invoice] = relationship(
        primaryjoin="and_(PaymentAllocation.invoice_id == Invoice.id, "
        "PaymentAllocation.organization_id == Invoice.organization_id)",
        foreign_keys="[PaymentAllocation.invoice_id, PaymentAllocation.organization_id]",
        viewonly=True,
        lazy="joined",
    )
