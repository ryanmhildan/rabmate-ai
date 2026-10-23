from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
from app.modules.identity.models import User
from app.modules.projects.models import Project
from app.modules.rab.calculation import DiscountType

if TYPE_CHECKING:
    from app.modules.pricing.models import PriceObservation


class RabStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


OPEN_STATUSES = (RabStatus.DRAFT, RabStatus.IN_REVIEW)


class RabItemType(StrEnum):
    MATERIAL = "material"
    LABOR = "labor"
    SERVICE = "service"
    EQUIPMENT = "equipment"
    TRANSPORT = "transport"
    OVERHEAD = "overhead"
    OTHER = "other"


class PriceSourceType(StrEnum):
    MANUAL = "manual"
    CATALOG = "catalog"
    HISTORY = "history"
    VENDOR_QUOTE = "vendor_quote"
    IMPORT = "import"
    EXTERNAL = "external"


class RabDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A RAB for a project. Content lives in its versions; only metadata here."""

    __tablename__ = "rab_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "id", name="uq_rab_documents_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_rab_documents_project_same_org",
        ),
        Index("ix_rab_documents_organization_id_project_id", "organization_id", "project_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    project_id: Mapped[uuid.UUID] = mapped_column()
    number: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    project: Mapped[Project] = relationship(
        primaryjoin="RabDocument.project_id == Project.id",
        foreign_keys=[project_id],
        viewonly=True,
        lazy="joined",
    )
    # Loaded explicitly (selectinload) where needed so list queries stay cheap.
    versions: Mapped[list[RabVersion]] = relationship(
        back_populates="rab",
        cascade="all, delete-orphan",
        order_by="RabVersion.version_no",
    )


class RabVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One revision of a RAB. Editable only while draft; approved versions are immutable."""

    __tablename__ = "rab_versions"
    __table_args__ = (
        UniqueConstraint("rab_id", "version_no"),
        UniqueConstraint("organization_id", "id", name="uq_rab_versions_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "rab_id"],
            ["rab_documents.organization_id", "rab_documents.id"],
            name="fk_rab_versions_rab_same_org",
            ondelete="CASCADE",
        ),
        # At most one version per RAB may be open (draft or in review) at any time.
        Index(
            "uq_rab_versions_one_open",
            "rab_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'in_review')"),
        ),
        Index("ix_rab_versions_organization_id_status", "organization_id", "status"),
        CheckConstraint("version_no >= 1", name="version_no_positive"),
        CheckConstraint(
            "(tax_label IS NULL) = (tax_rate_percent IS NULL)", name="tax_label_and_rate"
        ),
        CheckConstraint(
            "tax_rate_percent IS NULL OR (tax_rate_percent >= 0 AND tax_rate_percent <= 100)",
            name="tax_rate_range",
        ),
        CheckConstraint(
            "(discount_type = 'none' AND discount_value = 0)"
            " OR (discount_type = 'percent' AND discount_value BETWEEN 0 AND 100)"
            " OR (discount_type = 'amount' AND discount_value >= 0)",
            name="discount_consistent",
        ),
        CheckConstraint(
            "subtotal >= 0 AND discount_amount >= 0 AND discount_amount <= subtotal"
            " AND tax_amount >= 0 AND grand_total >= 0",
            name="totals_non_negative",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    rab_id: Mapped[uuid.UUID] = mapped_column()
    version_no: Mapped[int]
    status: Mapped[RabStatus] = mapped_column(str_enum(RabStatus, "rab_status"))
    based_on_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rab_versions.id"))
    currency: Mapped[str] = mapped_column(String(3))

    tax_label: Mapped[str | None] = mapped_column(String(32))
    tax_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_type: Mapped[DiscountType] = mapped_column(
        str_enum(DiscountType, "rab_discount_type"), default=DiscountType.NONE
    )
    discount_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[str | None] = mapped_column(Text)

    # Derived by app.modules.rab.calculation on every change; stored for listing and reporting.
    subtotal: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    taxable_base: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    unpriced_items: Mapped[int] = mapped_column(default=0)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    lock_version: Mapped[int] = mapped_column(default=1, server_default="1")

    rab: Mapped[RabDocument] = relationship(
        back_populates="versions",
        primaryjoin="RabVersion.rab_id == RabDocument.id",
        foreign_keys=[rab_id],
    )
    items: Mapped[list[RabItem]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="RabItem.position",
    )
    submitted_by: Mapped[User | None] = relationship(foreign_keys=[submitted_by_id], lazy="joined")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")

    __mapper_args__ = {"version_id_col": lock_version}


class RabItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rab_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "version_id"],
            ["rab_versions.organization_id", "rab_versions.id"],
            name="fk_rab_items_version_same_org",
            ondelete="CASCADE",
        ),
        # Provenance: the catalog price this item's unit price was taken from (same org only).
        ForeignKeyConstraint(
            ["organization_id", "price_observation_id"],
            ["price_observations.organization_id", "price_observations.id"],
            name="fk_rab_items_observation_same_org",
        ),
        Index("ix_rab_items_version_id_position", "version_id", "position"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("(unit_price IS NULL) = (subtotal IS NULL)", name="subtotal_iff_price"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    version_id: Mapped[uuid.UUID] = mapped_column()
    position: Mapped[int]
    code: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(100))
    item_type: Mapped[RabItemType] = mapped_column(str_enum(RabItemType, "rab_item_type"))
    specification: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    price_source_type: Mapped[PriceSourceType | None] = mapped_column(
        str_enum(PriceSourceType, "rab_price_source_type")
    )
    price_source: Mapped[str | None] = mapped_column(String(500))
    price_observation_id: Mapped[uuid.UUID | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(default=1, server_default="1")

    price_observation: Mapped[PriceObservation | None] = relationship(
        primaryjoin="RabItem.price_observation_id == PriceObservation.id",
        foreign_keys=[price_observation_id],
        viewonly=True,
        lazy="joined",
    )
    version: Mapped[RabVersion] = relationship(
        back_populates="items",
        primaryjoin="RabItem.version_id == RabVersion.id",
        foreign_keys=[version_id],
    )

    __mapper_args__ = {"version_id_col": row_version}
