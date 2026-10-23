"""SPK (Surat Perintah Kerja) and BAST (Berita Acara Serah Terima).

SPK: the work order for an accepted quotation — parties, scope, period, contract value (copied
from the quotation) and the signatories both parties name themselves.
BAST: a record of what was actually handed over under an SPK — dated, with parties and items.
Delivered volumes of contract items are checked against the contract (cumulative across BASTs).
Both follow the shared review workflow; numbers are assigned at issuance.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.billing.models import DocStatus, Quotation, WorkflowColumns
from app.modules.clients.models import Client
from app.modules.identity.models import User
from app.modules.projects.models import Project


class BastKind(StrEnum):
    PARTIAL = "partial"
    FINAL = "final"


class Spk(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowColumns, Base):
    __tablename__ = "spk_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "id", name="uq_spk_documents_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_spk_documents_project_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_spk_documents_client_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "quotation_id"],
            ["quotations.organization_id", "quotations.id"],
            name="fk_spk_documents_quotation_same_org",
        ),
        # One valid SPK per quotation.
        Index(
            "uq_spk_documents_one_per_quotation",
            "quotation_id",
            unique=True,
            postgresql_where=text("status <> 'void'"),
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="period_ordered",
        ),
        CheckConstraint("contract_value >= 0", name="value_non_negative"),
        CheckConstraint(
            "status NOT IN ('issued', 'void') OR (number IS NOT NULL AND issue_date IS NOT NULL)",
            name="issued_has_number",
        ),
        CheckConstraint("(status = 'void') = (voided_at IS NOT NULL)", name="void_timestamped"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    number: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[DocStatus] = mapped_column(str_enum(DocStatus, "spk_status"))
    project_id: Mapped[uuid.UUID] = mapped_column()
    client_id: Mapped[uuid.UUID] = mapped_column()
    quotation_id: Mapped[uuid.UUID] = mapped_column()
    title: Mapped[str] = mapped_column(String(300))
    issue_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(300))
    scope: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # Copied from the quotation at creation (the quotation is issued and immutable).
    currency: Mapped[str] = mapped_column(String(3))
    contract_value: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    # Typed in by users; printed under the signature lines. Never generated.
    client_signatory_name: Mapped[str | None] = mapped_column(String(200))
    client_signatory_title: Mapped[str | None] = mapped_column(String(200))
    company_signatory_name: Mapped[str | None] = mapped_column(String(200))
    company_signatory_title: Mapped[str | None] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    project: Mapped[Project] = relationship(
        primaryjoin="Spk.project_id == Project.id",
        foreign_keys="[Spk.project_id]",
        viewonly=True,
        lazy="joined",
    )
    client: Mapped[Client] = relationship(
        primaryjoin="Spk.client_id == Client.id",
        foreign_keys="[Spk.client_id]",
        viewonly=True,
        lazy="joined",
    )
    quotation: Mapped[Quotation] = relationship(
        primaryjoin="Spk.quotation_id == Quotation.id",
        foreign_keys="[Spk.quotation_id]",
        viewonly=True,
        lazy="joined",
    )
    submitted_by: Mapped[User | None] = relationship(
        foreign_keys="Spk.submitted_by_id", lazy="joined"
    )
    decided_by: Mapped[User | None] = relationship(foreign_keys="Spk.decided_by_id", lazy="joined")


class Bast(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowColumns, Base):
    __tablename__ = "bast_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "id", name="uq_bast_documents_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "spk_id"],
            ["spk_documents.organization_id", "spk_documents.id"],
            name="fk_bast_documents_spk_same_org",
        ),
        # At most one valid final handover per SPK.
        Index(
            "uq_bast_documents_one_final_per_spk",
            "spk_id",
            unique=True,
            postgresql_where=text("kind = 'final' AND status <> 'void'"),
        ),
        Index("ix_bast_documents_spk_id", "spk_id"),
        CheckConstraint(
            "status NOT IN ('issued', 'void') "
            "OR (number IS NOT NULL AND handover_date IS NOT NULL)",
            name="issued_has_number",
        ),
        CheckConstraint("(status = 'void') = (voided_at IS NOT NULL)", name="void_timestamped"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    number: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[DocStatus] = mapped_column(str_enum(DocStatus, "bast_status"))
    kind: Mapped[BastKind] = mapped_column(str_enum(BastKind, "bast_kind"))
    spk_id: Mapped[uuid.UUID] = mapped_column()
    title: Mapped[str] = mapped_column(String(300))
    handover_date: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(300))
    delivered_by_name: Mapped[str | None] = mapped_column(String(200))
    delivered_by_title: Mapped[str | None] = mapped_column(String(200))
    received_by_name: Mapped[str | None] = mapped_column(String(200))
    received_by_title: Mapped[str | None] = mapped_column(String(200))
    terms: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    spk: Mapped[Spk] = relationship(
        primaryjoin="Bast.spk_id == Spk.id",
        foreign_keys="[Bast.spk_id]",
        viewonly=True,
        lazy="joined",
    )
    items: Mapped[list[BastItem]] = relationship(
        back_populates="bast",
        primaryjoin="Bast.id == BastItem.bast_id",
        foreign_keys="[BastItem.bast_id]",
        order_by="BastItem.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    submitted_by: Mapped[User | None] = relationship(
        foreign_keys="Bast.submitted_by_id", lazy="joined"
    )
    decided_by: Mapped[User | None] = relationship(foreign_keys="Bast.decided_by_id", lazy="joined")


class BastItem(UUIDPrimaryKeyMixin, Base):
    """One delivered line; `rab_item_id` links it to a contract item (else it is extra work)."""

    __tablename__ = "bast_items"
    __table_args__ = (
        UniqueConstraint("bast_id", "position"),
        ForeignKeyConstraint(
            ["organization_id", "bast_id"],
            ["bast_documents.organization_id", "bast_documents.id"],
            name="fk_bast_items_bast_same_org",
            ondelete="CASCADE",
        ),
        Index("ix_bast_items_rab_item_id", "rab_item_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    bast_id: Mapped[uuid.UUID] = mapped_column()
    position: Mapped[int]
    rab_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rab_items.id"))
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(32))
    condition: Mapped[str | None] = mapped_column(String(500))

    bast: Mapped[Bast] = relationship(
        back_populates="items",
        primaryjoin="BastItem.bast_id == Bast.id",
        foreign_keys=[bast_id],
    )
