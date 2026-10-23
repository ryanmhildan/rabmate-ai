from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.modules.approvals.models import ApprovalAction
from app.modules.identity.schemas import UserBrief, blank_to_none
from app.modules.rab.calculation import DiscountType
from app.modules.rab.compare import ChangeKind
from app.modules.rab.lifecycle import RabAction
from app.modules.rab.models import PriceSourceType, RabItemType, RabStatus
from app.modules.rab.validation import Severity
from app.shared.money import ExactDecimal, Money, Percent

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalText = Annotated[
    str | None, StringConstraints(max_length=10_000), AfterValidator(blank_to_none)
]
Short = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=100),
    AfterValidator(blank_to_none),
]
Quantity = Annotated[Decimal, ExactDecimal, Field(gt=0, max_digits=18, decimal_places=4)]
UnitPrice = Annotated[Decimal, ExactDecimal, Field(ge=0, max_digits=20, decimal_places=4)]
TaxLabel = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=32),
    AfterValidator(blank_to_none),
]
Note = Annotated[str | None, StringConstraints(max_length=2000), AfterValidator(blank_to_none)]


# --------------------------------------------------------------------------- inputs


class RabCreate(BaseModel):
    title: Title
    notes: OptionalText = None


class RabUpdate(BaseModel):
    title: Title


class VersionUpdate(BaseModel):
    """Header of a draft version. `lock_version` must match the version last read."""

    lock_version: Annotated[int, Field(ge=1)]
    tax_label: TaxLabel = None
    tax_rate_percent: Percent | None = None
    discount_type: DiscountType | None = None
    discount_value: Money | None = None
    notes: OptionalText = None
    assumptions: OptionalText = None


class ItemBase(BaseModel):
    code: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=50),
        AfterValidator(blank_to_none),
    ] = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    category: Short = None
    item_type: RabItemType = RabItemType.MATERIAL
    specification: OptionalText = None
    quantity: Quantity
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    unit_price: UnitPrice | None = None
    price_source_type: PriceSourceType | None = None
    price_source: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=500),
        AfterValidator(blank_to_none),
    ] = None
    notes: OptionalText = None
    # When set, the server takes unit price and source from this catalog price
    # (unit_price / price_source sent alongside are ignored).
    price_observation_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _source_type_needs_price(self) -> Self:
        if self.price_observation_id is not None:
            return self
        if self.unit_price is None and self.price_source_type is not None:
            raise ValueError("Jenis sumber harga hanya diisi bila harga satuan diisi.")
        return self


class ItemCreate(ItemBase):
    pass


class ItemUpdate(ItemBase):
    """Full replacement of an item's fields. `row_version` must match the item last read."""

    row_version: Annotated[int, Field(ge=1)]


class TransitionRequest(BaseModel):
    note: Note = None


class NewVersionRequest(BaseModel):
    from_version_no: Annotated[int, Field(ge=1)] | None = None


class DuplicateRequest(BaseModel):
    project_id: uuid.UUID | None = None
    title: Title | None = None
    version_no: Annotated[int, Field(ge=1)] | None = None


# --------------------------------------------------------------------------- outputs


class ProjectRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    name: str


class Totals(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subtotal: Decimal
    discount_amount: Decimal
    taxable_base: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    unpriced_items: int


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    code: str | None
    name: str
    category: str | None
    item_type: RabItemType
    specification: str | None
    quantity: Decimal
    unit: str
    unit_price: Decimal | None
    subtotal: Decimal | None
    price_source_type: PriceSourceType | None
    price_source: str | None
    notes: str | None
    row_version: int
    price_observation_id: uuid.UUID | None
    price_verification_status: str | None


class IssueOut(BaseModel):
    severity: Severity
    code: str
    message: str
    item_id: uuid.UUID | None


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: ApprovalAction
    from_status: str
    to_status: str
    actor: UserBrief | None
    note: str | None
    created_at: datetime


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_no: int
    status: RabStatus
    grand_total: Decimal
    currency: str
    created_at: datetime
    decided_at: datetime | None


class VersionOut(VersionSummary):
    based_on_version_id: uuid.UUID | None
    tax_label: str | None
    tax_rate_percent: Decimal | None
    discount_type: DiscountType
    discount_value: Decimal
    notes: str | None
    assumptions: str | None
    totals: Totals
    items: list[ItemOut]
    issues: list[IssueOut]
    approvals: list[ApprovalOut]
    submitted_by: UserBrief | None
    submitted_at: datetime | None
    decided_by: UserBrief | None
    lock_version: int
    editable: bool
    allowed_actions: list[RabAction]
    can_create_version: bool


class RabListItem(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    project: ProjectRef
    latest_version_no: int
    latest_status: RabStatus
    currency: str
    grand_total: Decimal
    updated_at: datetime


class RabOut(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    project: ProjectRef
    versions: list[VersionSummary]
    created_at: datetime
    updated_at: datetime


class CompareLine(BaseModel):
    kind: ChangeKind
    code: str | None
    name: str
    unit: str
    before_quantity: Decimal | None
    after_quantity: Decimal | None
    before_unit_price: Decimal | None
    after_unit_price: Decimal | None
    before_subtotal: Decimal | None
    after_subtotal: Decimal | None
    subtotal_delta: Decimal
    changed_fields: list[str]


class CompareOut(BaseModel):
    from_version_no: int
    to_version_no: int
    currency: str
    lines: list[CompareLine]
    before_totals: Totals
    after_totals: Totals
    grand_total_delta: Decimal


class PendingApproval(BaseModel):
    rab_id: uuid.UUID
    number: str
    title: str
    project: ProjectRef
    version_no: int
    currency: str
    grand_total: Decimal
    submitted_by: UserBrief | None
    submitted_at: datetime | None
