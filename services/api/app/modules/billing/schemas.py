from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.billing.invoicing import PaymentState
from app.modules.billing.models import (
    ClientResponse,
    DocStatus,
    InvoiceKind,
    PaymentMethod,
    PaymentStatus,
    TermBasis,
)
from app.modules.identity.schemas import UserBrief, blank_to_none
from app.modules.rab.schemas import ApprovalOut, Quantity, UnitPrice
from app.shared.money import ExactDecimal, Percent

Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
LongText = Annotated[
    str | None, StringConstraints(max_length=10_000), AfterValidator(blank_to_none)
]
Note = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=1000),
    AfterValidator(blank_to_none),
]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
TermName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Short500 = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=500),
    AfterValidator(blank_to_none),
]
Reference = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=200),
    AfterValidator(blank_to_none),
]
TaxLabel = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=32),
    AfterValidator(blank_to_none),
]
LineText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
TermValue = Annotated[Decimal, ExactDecimal, Field(gt=0, max_digits=20, decimal_places=2)]
PositiveMoney = Annotated[Decimal, ExactDecimal, Field(gt=0, max_digits=20, decimal_places=2)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class Brief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str | None
    name: str


class RefBrief(BaseModel):
    id: uuid.UUID
    number: str | None


class TransitionIn(BaseModel):
    note: Note = None


class VoidIn(BaseModel):
    reason: Reason


# --------------------------------------------------------------------------- quotations


class QuotationCreate(BaseModel):
    rab_version_id: uuid.UUID
    subject: Subject | None = None


class QuotationUpdate(BaseModel):
    version: Annotated[int, Field(ge=1)]
    subject: Subject
    valid_until: date | None = None
    introduction: LongText = None
    scope: LongText = None
    terms: LongText = None
    notes: LongText = None


class TermIn(BaseModel):
    name: TermName
    basis: TermBasis
    # A percentage (0 < p <= 100) or an amount before tax, depending on `basis`.
    value: TermValue
    due_date: date | None = None
    description: Short500 = None


class TermsUpdate(BaseModel):
    version: Annotated[int, Field(ge=1)]
    terms: Annotated[list[TermIn], Field(max_length=20)]


class ResponseIn(BaseModel):
    response: ClientResponse
    note: Note = None


class InvoiceBrief(BaseModel):
    id: uuid.UUID
    number: str | None
    status: DocStatus
    payment_state: PaymentState | None


class TermOut(BaseModel):
    id: uuid.UUID
    position: int
    name: str
    basis: TermBasis
    percent: Decimal | None
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    due_date: date | None
    description: str | None
    invoice: InvoiceBrief | None


class QuotationListItem(BaseModel):
    id: uuid.UUID
    number: str
    status: DocStatus
    subject: str
    project: Brief
    client: Brief | None
    rab: RefBrief
    rab_version_no: int
    currency: str
    grand_total: Decimal
    valid_until: date | None
    expired: bool
    client_response: ClientResponse | None
    created_at: datetime
    updated_at: datetime


class SpkBrief(BaseModel):
    id: uuid.UUID
    number: str | None
    status: DocStatus


class QuotationOut(QuotationListItem):
    introduction: str | None
    scope: str | None
    terms: str | None
    notes: str | None
    subtotal: Decimal
    discount_amount: Decimal
    taxable_base: Decimal
    tax_label: str | None
    tax_rate_percent: Decimal | None
    tax_amount: Decimal
    payment_terms: list[TermOut]
    responded_at: datetime | None
    response_note: str | None
    submitted_by: UserBrief | None
    submitted_at: datetime | None
    decided_by: UserBrief | None
    decided_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    version: int
    approvals: list[ApprovalOut]
    allowed_actions: list[str]
    editable: bool
    can_issue: bool
    can_respond: bool
    can_void: bool
    can_delete: bool
    can_invoice: bool
    spk: SpkBrief | None
    can_create_spk: bool


# --------------------------------------------------------------------------- invoices


class InvoiceLineIn(BaseModel):
    description: LineText
    quantity: Quantity
    unit: Unit
    unit_price: UnitPrice


class InvoiceCreate(BaseModel):
    project_id: uuid.UUID
    title: Subject
    due_date: date | None = None
    notes: LongText = None


class InvoiceUpdate(BaseModel):
    version: Annotated[int, Field(ge=1)]
    title: Subject
    due_date: date | None = None
    notes: LongText = None
    # Manual invoices only (term invoices keep the schedule's figures).
    tax_label: TaxLabel = None
    tax_rate_percent: Percent | None = None
    items: Annotated[list[InvoiceLineIn], Field(max_length=200)] | None = None


class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    amount: Decimal


class AllocationOut(BaseModel):
    payment_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str | None
    payment_date: date
    method: PaymentMethod
    reference: str | None
    amount: Decimal
    payment_status: PaymentStatus


class TermRef(BaseModel):
    id: uuid.UUID
    name: str
    percent: Decimal | None


class InvoiceListItem(BaseModel):
    id: uuid.UUID
    number: str | None
    kind: InvoiceKind
    status: DocStatus
    title: str
    project: Brief
    client: Brief
    quotation: RefBrief | None
    issue_date: date | None
    due_date: date | None
    currency: str
    grand_total: Decimal
    amount_paid: Decimal
    outstanding: Decimal
    payment_state: PaymentState | None
    overdue: bool
    created_at: datetime


class InvoiceOut(InvoiceListItem):
    payment_term: TermRef | None
    tax_label: str | None
    tax_rate_percent: Decimal | None
    subtotal: Decimal
    tax_amount: Decimal
    notes: str | None
    items: list[InvoiceLineOut]
    allocations: list[AllocationOut]
    submitted_by: UserBrief | None
    submitted_at: datetime | None
    decided_by: UserBrief | None
    decided_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    version: int
    approvals: list[ApprovalOut]
    allowed_actions: list[str]
    editable: bool
    lines_editable: bool
    can_issue: bool
    can_void: bool
    can_delete: bool
    can_record_payment: bool


# --------------------------------------------------------------------------- payments


class AllocationIn(BaseModel):
    invoice_id: uuid.UUID
    amount: PositiveMoney


class PaymentCreate(BaseModel):
    client_id: uuid.UUID
    payment_date: date
    amount: PositiveMoney
    currency: Currency = "IDR"
    method: PaymentMethod
    reference: Reference = None
    notes: LongText = None
    allocations: Annotated[list[AllocationIn], Field(max_length=50)] = []


class PaymentOut(BaseModel):
    id: uuid.UUID
    client: Brief
    payment_date: date
    amount: Decimal
    currency: str
    method: PaymentMethod
    reference: str | None
    notes: str | None
    status: PaymentStatus
    allocated: Decimal
    unallocated: Decimal
    allocations: list[AllocationOut]
    recorded_by: UserBrief | None
    created_at: datetime
    voided_at: datetime | None
    voided_by: UserBrief | None
    void_reason: str | None


class AllocateIn(BaseModel):
    invoice_id: uuid.UUID
    amount: PositiveMoney
