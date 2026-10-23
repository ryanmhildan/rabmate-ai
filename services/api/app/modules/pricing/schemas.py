from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.modules.identity.schemas import (
    LongText,
    OptionalEmail,
    Phone,
    ShortText,
    UserBrief,
    blank_to_none,
)
from app.modules.pricing.matching import MatchLevel
from app.modules.pricing.models import ImportStatus, ObservationSource, VerificationStatus
from app.modules.rab.models import RabItemType
from app.shared.money import ExactDecimal

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
SupplierName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
OptionalUnit = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=32),
    AfterValidator(blank_to_none),
]
Code = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=50),
    AfterValidator(blank_to_none),
]
Label100 = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=100),
    AfterValidator(blank_to_none),
]
Reference = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=500),
    AfterValidator(blank_to_none),
]
Note1000 = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=1000),
    AfterValidator(blank_to_none),
]


def _http_url(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.lower().startswith(("http://", "https://")) or " " in value:
        raise ValueError("Hanya URL http/https yang diterima.")
    return value


UnitPrice = Annotated[Decimal, ExactDecimal, Field(ge=0, max_digits=20, decimal_places=4)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
HttpUrl = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=1000),
    AfterValidator(blank_to_none),
    AfterValidator(_http_url),
]


# --------------------------------------------------------------------------- suppliers


class SupplierIn(BaseModel):
    name: SupplierName
    contact_person: ShortText = None
    phone: Phone = None
    email: OptionalEmail = None
    city: ShortText = None
    address: LongText = None
    notes: LongText = None


class SupplierUpdate(SupplierIn):
    version: Annotated[int, Field(ge=1)]
    is_active: bool = True


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contact_person: str | None
    phone: str | None
    email: str | None
    city: str | None
    address: str | None
    notes: str | None
    is_active: bool
    version: int


class SupplierBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


# --------------------------------------------------------------------------- observations


class ObservationIn(BaseModel):
    price: UnitPrice
    currency: Currency = "IDR"
    unit: OptionalUnit = None  # defaults to the item's unit
    supplier_id: uuid.UUID | None = None
    source_type: ObservationSource = ObservationSource.MANUAL
    source_reference: Reference = None
    source_url: HttpUrl = None
    observed_specification: LongText = None
    observed_at: date
    valid_from: date | None = None
    valid_until: date | None = None
    location: Label100 = None
    notes: LongText = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        start = self.valid_from or self.observed_at
        if self.valid_until is not None and self.valid_until < start:
            raise ValueError(
                "Tanggal berlaku sampai tidak boleh sebelum tanggal berlaku/diperoleh."
            )
        if self.source_type is ObservationSource.IMPORT:
            raise ValueError("Sumber 'import' hanya dibuat oleh proses impor spreadsheet.")
        return self


class VerificationIn(BaseModel):
    status: Literal["verified", "rejected"]
    note: Note1000 = None


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    catalog_item_id: uuid.UUID
    price: Decimal
    currency: str
    unit: str
    supplier: SupplierBrief | None
    source_type: ObservationSource
    source_reference: str | None
    source_url: str | None
    observed_specification: str | None
    match_level: MatchLevel | None
    observed_at: date
    valid_from: date | None
    valid_until: date | None
    location: str | None
    verification_status: VerificationStatus
    verified_by: UserBrief | None
    verified_at: datetime | None
    verification_note: str | None
    notes: str | None
    import_job_id: uuid.UUID | None
    created_at: datetime


# --------------------------------------------------------------------------- catalog items


class CatalogItemIn(BaseModel):
    code: Code = None
    name: Name
    category: Label100 = None
    brand: Label100 = None
    specification: LongText = None
    unit: Unit
    item_type: RabItemType = RabItemType.MATERIAL
    notes: LongText = None


class CatalogItemCreate(CatalogItemIn):
    initial_price: ObservationIn | None = None


class CatalogItemUpdate(CatalogItemIn):
    version: Annotated[int, Field(ge=1)]
    is_active: bool = True


class PriceSummary(BaseModel):
    """Latest prices for list views. Verified and unverified are kept apart on purpose."""

    latest_verified: ObservationOut | None
    latest_any: ObservationOut | None
    observation_count: int


class CatalogItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    name: str
    category: str | None
    brand: str | None
    specification: str | None
    unit: str
    item_type: RabItemType
    is_active: bool
    notes: str | None
    version: int
    updated_at: datetime


class CatalogListItem(CatalogItemOut):
    prices: PriceSummary


class CatalogItemDetail(CatalogItemOut):
    observations: list[ObservationOut]
    prices: PriceSummary


# --------------------------------------------------------------------------- candidates


class CandidateOut(BaseModel):
    kind: Literal["catalog", "history"]
    score: int
    level: MatchLevel
    unit_compatible: bool
    reasons: list[str]
    warnings: list[str]
    name: str
    unit: str
    brand: str | None
    specification: str | None
    price: Decimal
    currency: str
    observed_at: date | None
    verified: bool
    # catalog candidates
    catalog_item_id: uuid.UUID | None = None
    observation_id: uuid.UUID | None = None
    supplier: str | None = None
    source_reference: str | None = None
    # history candidates (prices from approved RAB versions)
    reference: str | None = None


class ExternalStatus(BaseModel):
    configured: bool
    provider: str | None
    message: str


# --------------------------------------------------------------------------- import


class ImportRowOut(BaseModel):
    row: int
    valid: bool
    errors: list[str]
    data: dict[str, Any]
    action: str | None


class ImportJobOut(BaseModel):
    id: uuid.UUID
    status: ImportStatus
    filename: str
    row_count: int
    valid_count: int
    error_count: int
    warnings: list[str]
    rows: list[ImportRowOut]
    result: dict[str, Any] | None
    created_at: datetime
    committed_at: datetime | None
