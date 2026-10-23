from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.documents.models import DocumentStatus, DocumentType, FileFormat
from app.modules.identity.schemas import UserBrief, blank_to_none

Tagline = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=200),
    AfterValidator(blank_to_none),
]
Footer = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=500),
    AfterValidator(blank_to_none),
]
Terms = Annotated[str | None, StringConstraints(max_length=5000), AfterValidator(blank_to_none)]
BankName = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=100),
    AfterValidator(blank_to_none),
]
AccountHolder = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=200),
    AfterValidator(blank_to_none),
]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
VoidReason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def _account_number(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    if not re.fullmatch(r"[0-9][0-9 .\-]{2,48}[0-9]", value):
        raise ValueError(
            "Nomor rekening hanya berisi angka (spasi, titik, atau tanda hubung boleh)."
        )
    return value


AccountNumber = Annotated[str | None, AfterValidator(_account_number)]


class DocumentSettingsFields(BaseModel):
    tagline: Tagline = None
    accent_color: HexColor = "#1F4E79"
    footer_text: Footer = None
    rab_terms: Terms = None
    show_item_codes: bool = True
    show_price_sources: bool = False
    show_amount_in_words: bool = True
    payment_bank_name: BankName = None
    payment_account_number: AccountNumber = None
    payment_account_holder: AccountHolder = None
    spk_terms: Terms = None
    bast_terms: Terms = None


class DocumentSettingsUpdate(DocumentSettingsFields):
    # 0 when the organization has never saved settings (defaults are in use).
    version: Annotated[int, Field(ge=0)]


class DocumentSettingsOut(DocumentSettingsFields):
    version: int
    updated_at: datetime | None


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    format: FileFormat
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_type: DocumentType
    status: DocumentStatus
    number: str
    title: str
    project_id: uuid.UUID | None
    rab_version_id: uuid.UUID | None
    quotation_id: uuid.UUID | None
    invoice_id: uuid.UUID | None
    spk_id: uuid.UUID | None
    bast_id: uuid.UUID | None
    currency: str
    total_amount: Decimal
    snapshot_sha256: str
    schema_version: int
    issued_at: datetime
    issued_by: UserBrief | None
    voided_at: datetime | None
    voided_by: UserBrief | None
    void_reason: str | None
    files: list[FileOut]


class DocumentDetail(DocumentOut):
    snapshot: dict[str, Any]


class VoidIn(BaseModel):
    reason: VoidReason
