from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.clients.models import ClientType
from app.modules.identity.schemas import (
    LongText,
    Name,
    OptionalEmail,
    Phone,
    ShortText,
    TaxId,
    blank_to_none,
)

ClientCode = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=32, pattern=r"^[A-Za-z0-9._\-]*$"),
    AfterValidator(blank_to_none),
]


class ClientBase(BaseModel):
    code: ClientCode = None
    name: Name
    client_type: ClientType = ClientType.COMPANY
    tax_id: TaxId = None
    email: OptionalEmail = None
    phone: Phone = None
    address: LongText = None
    city: ShortText = None
    contact_person: ShortText = None
    notes: LongText = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    """Partial update. `version` must equal the version the client last read."""

    version: Annotated[int, Field(ge=1)]
    code: ClientCode = None
    name: Name | None = None
    client_type: ClientType | None = None
    tax_id: TaxId = None
    email: OptionalEmail = None
    phone: Phone = None
    address: LongText = None
    city: ShortText = None
    contact_person: ShortText = None
    notes: LongText = None
    is_active: bool | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    name: str
    client_type: ClientType
    tax_id: str | None
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    contact_person: str | None
    notes: str | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ClientBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    name: str
