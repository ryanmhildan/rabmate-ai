from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import str_enum


class ClientType(StrEnum):
    COMPANY = "company"
    INDIVIDUAL = "individual"
    GOVERNMENT = "government"
    OTHER = "other"


class Client(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        # Target for composite FKs so other tables cannot reference another org's client.
        UniqueConstraint("organization_id", "id", name="uq_clients_organization_id_id"),
        Index("ix_clients_organization_id_name", "organization_id", "name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    code: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    client_type: Mapped[ClientType] = mapped_column(str_enum(ClientType, "client_type"))
    tax_id: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}
