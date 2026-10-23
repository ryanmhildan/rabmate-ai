from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.billing.models import DocStatus
from app.modules.billing.schemas import (
    Brief,
    LineText,
    LongText,
    RefBrief,
    Short500,
    Subject,
    TermOut,
    Unit,
)
from app.modules.identity.schemas import UserBrief, blank_to_none
from app.modules.rab.schemas import ApprovalOut, Quantity
from app.modules.workorders.models import BastKind

Name = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=200),
    AfterValidator(blank_to_none),
]
Place = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=300),
    AfterValidator(blank_to_none),
]


# --------------------------------------------------------------------------- SPK


class SpkCreate(BaseModel):
    quotation_id: uuid.UUID
    title: Subject | None = None


class SpkUpdate(BaseModel):
    version: Annotated[int, Field(ge=1)]
    title: Subject
    start_date: date | None = None
    end_date: date | None = None
    location: Place = None
    scope: LongText = None
    terms: LongText = None
    notes: LongText = None
    client_signatory_name: Name = None
    client_signatory_title: Name = None
    company_signatory_name: Name = None
    company_signatory_title: Name = None


class SpkListItem(BaseModel):
    id: uuid.UUID
    number: str | None
    status: DocStatus
    title: str
    project: Brief
    client: Brief
    quotation: RefBrief
    currency: str
    contract_value: Decimal
    issue_date: date | None
    start_date: date | None
    end_date: date | None
    bast_count: int
    created_at: datetime
    updated_at: datetime


class SpkOut(SpkListItem):
    location: str | None
    scope: str | None
    terms: str | None
    notes: str | None
    client_signatory_name: str | None
    client_signatory_title: str | None
    company_signatory_name: str | None
    company_signatory_title: str | None
    taxable_base: Decimal
    tax_label: str | None
    tax_rate_percent: Decimal | None
    tax_amount: Decimal
    payment_terms: list[TermOut]
    rab: RefBrief
    rab_version_no: int
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
    can_void: bool
    can_delete: bool
    can_create_bast: bool


class ContractItemProgress(BaseModel):
    """A contract (RAB) item with the volumes handed over so far under one SPK."""

    rab_item_id: uuid.UUID
    no: int
    code: str | None
    name: str
    category: str | None
    unit: str
    contract_quantity: Decimal
    delivered_quantity: Decimal  # issued BASTs
    pending_quantity: Decimal  # BASTs still in draft / review / approved
    remaining_quantity: Decimal  # contract - delivered (never below 0)


class SpkProgress(BaseModel):
    spk_id: uuid.UUID
    items: list[ContractItemProgress]
    final_bast: RefBrief | None


# --------------------------------------------------------------------------- BAST


class BastCreate(BaseModel):
    spk_id: uuid.UUID
    kind: BastKind
    title: Subject | None = None
    # Pre-fills the lines with every contract item's remaining volume (to be reviewed by the user).
    prefill_remaining: bool = False


class BastItemIn(BaseModel):
    rab_item_id: uuid.UUID | None = None
    description: LineText
    quantity: Quantity
    unit: Unit
    condition: Short500 = None


class BastUpdate(BaseModel):
    version: Annotated[int, Field(ge=1)]
    title: Subject
    handover_date: date | None = None
    location: Place = None
    delivered_by_name: Name = None
    delivered_by_title: Name = None
    received_by_name: Name = None
    received_by_title: Name = None
    terms: LongText = None
    notes: LongText = None
    # None keeps the current lines.
    items: Annotated[list[BastItemIn], Field(max_length=500)] | None = None


class BastItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    rab_item_id: uuid.UUID | None
    description: str
    quantity: Decimal
    unit: str
    condition: str | None


class BastListItem(BaseModel):
    id: uuid.UUID
    number: str | None
    status: DocStatus
    kind: BastKind
    title: str
    spk: RefBrief
    project: Brief
    client: Brief
    handover_date: date | None
    item_count: int
    created_at: datetime
    updated_at: datetime


class BastOut(BastListItem):
    location: str | None
    delivered_by_name: str | None
    delivered_by_title: str | None
    received_by_name: str | None
    received_by_title: str | None
    terms: str | None
    notes: str | None
    items: list[BastItemOut]
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
    can_void: bool
    can_delete: bool
