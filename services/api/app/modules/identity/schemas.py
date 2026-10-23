from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.modules.identity.permissions import ROLE_LABELS, Permission, Role

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalText = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)]
Password = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]

_PHONE = re.compile(r"^[0-9+()\-\s.]{6,32}$")


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _optional_tax_id(value: str | None) -> str | None:
    """Indonesian NPWP: 15 digits (legacy) or 16 digits (NIK-based), separators allowed."""
    if value is None or not value.strip():
        return None
    digits = re.sub(r"[.\-\s]", "", value)
    if not digits.isdigit() or len(digits) not in (15, 16):
        raise ValueError("NPWP harus terdiri dari 15 atau 16 digit.")
    return value.strip()


def _optional_phone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if not _PHONE.match(value.strip()):
        raise ValueError("Nomor telepon tidak valid.")
    return value.strip()


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]
TaxId = Annotated[str | None, AfterValidator(_optional_tax_id)]
Phone = Annotated[str | None, AfterValidator(_optional_phone)]
OptionalEmail = Annotated[EmailStr | None, AfterValidator(lambda v: v.lower() if v else None)]
LongText = Annotated[str | None, StringConstraints(max_length=5000), AfterValidator(blank_to_none)]
ShortText = Annotated[str | None, StringConstraints(max_length=200), AfterValidator(blank_to_none)]


# --------------------------------------------------------------------------- auth


class LoginRequest(BaseModel):
    email: NormalizedEmail
    # No length rules on login: policy is enforced when passwords are set.
    password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]
    organization_id: uuid.UUID | None = None


class ChangePasswordRequest(BaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]
    new_password: Password


class SwitchOrganizationRequest(BaseModel):
    organization_id: uuid.UUID


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str


class OrganizationBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class OrganizationChoice(OrganizationBrief):
    role: Role


class MeResponse(BaseModel):
    user: UserBrief
    organization: OrganizationBrief
    role: Role
    role_label: str
    permissions: list[Permission]
    organizations: list[OrganizationChoice]


# --------------------------------------------------------------------------- organization


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    legal_name: str | None
    tax_id: str | None
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    website: str | None
    updated_at: datetime


class OrganizationUpdate(BaseModel):
    name: Name | None = None
    legal_name: ShortText = None
    tax_id: TaxId = None
    email: OptionalEmail = None
    phone: Phone = None
    address: LongText = None
    city: ShortText = None
    website: ShortText = None


# --------------------------------------------------------------------------- users


class RoleOut(BaseModel):
    role: Role
    label: str
    permissions: list[Permission]


class MemberOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    role_label: str
    is_active: bool
    last_login_at: datetime | None
    joined_at: datetime


class MemberCreate(BaseModel):
    email: NormalizedEmail
    full_name: Name
    role: Role
    # Required only when the e-mail is not registered yet.
    password: Password | None = None


class MemberUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


def role_label(role: Role) -> str:
    return ROLE_LABELS[role]
