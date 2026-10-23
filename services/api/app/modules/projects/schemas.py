from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)

from app.modules.clients.schemas import ClientBrief
from app.modules.identity.schemas import LongText, Name, ShortText, UserBrief, blank_to_none
from app.modules.projects.lifecycle import allowed_transitions
from app.modules.projects.models import ProjectMemberRole, ProjectStatus, ProjectType
from app.shared.money import Money, Percent

MAX_ATTRIBUTES = 30
_ATTRIBUTE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,49}$")

AttributeValue = str | int | bool | None


def _validate_attributes(value: dict[str, AttributeValue]) -> dict[str, AttributeValue]:
    if len(value) > MAX_ATTRIBUTES:
        raise ValueError(f"Maksimal {MAX_ATTRIBUTES} atribut tambahan.")
    for key, item in value.items():
        if not _ATTRIBUTE_KEY.match(key):
            raise ValueError(
                f"Nama atribut '{key}' tidak valid (huruf kecil, angka, garis bawah; maks. 50)."
            )
        if isinstance(item, str) and len(item) > 500:
            raise ValueError(f"Nilai atribut '{key}' terlalu panjang (maks. 500 karakter).")
    return value


Attributes = Annotated[dict[str, AttributeValue], AfterValidator(_validate_attributes)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
TaxLabel = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=32),
    AfterValidator(blank_to_none),
]
TaxRate = Percent | None
OptionalMoney = Money | None
ProjectNumber = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=32, pattern=r"^[A-Za-z0-9/._\-]*$"),
    AfterValidator(blank_to_none),
]


def check_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise ValueError("Tanggal selesai tidak boleh sebelum tanggal mulai.")


def check_tax(label: str | None, rate: Decimal | None) -> None:
    if (label is None) != (rate is None):
        raise ValueError("Label pajak dan tarif pajak harus diisi bersamaan atau dikosongkan.")


class ProjectCreate(BaseModel):
    number: ProjectNumber = Field(default=None, description="Kosongkan untuk penomoran otomatis")
    name: Name
    project_type: ProjectType
    client_id: uuid.UUID | None = None
    description: LongText = None
    scope: LongText = None
    location: ShortText = None
    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus = ProjectStatus.PROSPECT
    currency: Currency = "IDR"
    tax_label: TaxLabel = None
    tax_rate_percent: TaxRate = None
    budget_amount: OptionalMoney = None
    notes: LongText = None
    attributes: Attributes = Field(default_factory=dict)
    owner_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        check_dates(self.start_date, self.end_date)
        check_tax(self.tax_label, self.tax_rate_percent)
        return self


class ProjectUpdate(BaseModel):
    version: Annotated[int, Field(ge=1)]
    name: Name | None = None
    project_type: ProjectType | None = None
    client_id: uuid.UUID | None = None
    description: LongText = None
    scope: LongText = None
    location: ShortText = None
    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus | None = None
    currency: Currency | None = None
    tax_label: TaxLabel = None
    tax_rate_percent: TaxRate = None
    budget_amount: OptionalMoney = None
    notes: LongText = None
    attributes: Attributes | None = None
    owner_id: uuid.UUID | None = None


class ProjectMemberIn(BaseModel):
    user_id: uuid.UUID
    role: ProjectMemberRole = ProjectMemberRole.MEMBER


class ProjectMembersUpdate(BaseModel):
    members: Annotated[list[ProjectMemberIn], Field(max_length=100)]


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserBrief
    role: ProjectMemberRole


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    name: str
    project_type: ProjectType
    status: ProjectStatus
    client: ClientBrief | None
    start_date: date | None
    end_date: date | None
    currency: str
    budget_amount: Decimal | None
    updated_at: datetime


class ProjectOut(ProjectListItem):
    description: str | None
    scope: str | None
    location: str | None
    tax_label: str | None
    tax_rate_percent: Decimal | None
    notes: str | None
    attributes: dict[str, Any]
    owner: UserBrief | None
    members: list[ProjectMemberOut]
    version: int
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed_status_transitions(self) -> list[ProjectStatus]:
        return allowed_transitions(self.status)
