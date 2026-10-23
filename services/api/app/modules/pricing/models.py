from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.identity.models import User
from app.modules.pricing.matching import MatchLevel
from app.modules.rab.models import RabItemType


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ObservationSource(StrEnum):
    MANUAL = "manual"
    VENDOR_QUOTE = "vendor_quote"
    IMPORT = "import"
    EXTERNAL = "external"


class ImportStatus(StrEnum):
    PREVIEWED = "previewed"
    COMMITTED = "committed"
    DISCARDED = "discarded"


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_suppliers_organization_id_id"),
        Index("ix_suppliers_organization_id_name", "organization_id", "name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    city: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


class PriceCatalogItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What is being priced. Prices themselves live in price_observations (history)."""

    __tablename__ = "price_catalog_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        UniqueConstraint("organization_id", "id", name="uq_price_catalog_items_organization_id_id"),
        Index("ix_price_catalog_items_organization_id_category", "organization_id", "category"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    code: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(100))
    specification: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    item_type: Mapped[RabItemType] = mapped_column(str_enum(RabItemType, "catalog_item_type"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


# Trigram index for candidate search (pg_trgm, enabled in migration 0004). Declared after the
# class so the operator class can be given via postgresql_ops (lets Alembic compare it).
Index(
    "ix_price_catalog_items_name_trgm",
    func.lower(PriceCatalogItem.__table__.c.name).label("name_lower"),
    postgresql_using="gin",
    postgresql_ops={"name_lower": "gin_trgm_ops"},
)


class PriceObservation(UUIDPrimaryKeyMixin, Base):
    """One price seen at one time from one source. Append-only: only verification changes."""

    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_price_observations_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "catalog_item_id"],
            ["price_catalog_items.organization_id", "price_catalog_items.id"],
            name="fk_price_observations_item_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "supplier_id"],
            ["suppliers.organization_id", "suppliers.id"],
            name="fk_price_observations_supplier_same_org",
        ),
        Index("ix_price_observations_item_observed", "catalog_item_id", "observed_at"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= COALESCE(valid_from, observed_at)",
            name="validity_ordered",
        ),
        # A price without any source can never be marked verified.
        CheckConstraint(
            "verification_status <> 'verified' OR source_reference IS NOT NULL"
            " OR source_url IS NOT NULL OR supplier_id IS NOT NULL",
            name="verified_requires_source",
        ),
        CheckConstraint(
            "(verification_status = 'unverified') = (verified_at IS NULL)",
            name="verification_timestamped",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    catalog_item_id: Mapped[uuid.UUID] = mapped_column()
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column()
    source_type: Mapped[ObservationSource] = mapped_column(
        str_enum(ObservationSource, "observation_source")
    )
    source_reference: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    observed_specification: Mapped[str | None] = mapped_column(Text)
    match_level: Mapped[MatchLevel | None] = mapped_column(str_enum(MatchLevel, "match_level"))
    observed_at: Mapped[date] = mapped_column(Date)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(100))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus, "verification_status"), default=VerificationStatus.UNVERIFIED
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_jobs.id"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    item: Mapped[PriceCatalogItem] = relationship(
        primaryjoin="PriceObservation.catalog_item_id == PriceCatalogItem.id",
        foreign_keys=[catalog_item_id],
        viewonly=True,
        lazy="joined",
    )
    supplier: Mapped[Supplier | None] = relationship(
        primaryjoin="PriceObservation.supplier_id == Supplier.id",
        foreign_keys=[supplier_id],
        viewonly=True,
        lazy="joined",
    )
    verified_by: Mapped[User | None] = relationship(foreign_keys=[verified_by_id], lazy="joined")


class ImportJob(UUIDPrimaryKeyMixin, Base):
    """A spreadsheet import: parsed + validated rows kept for preview until committed.

    The uploaded file itself is not stored; only the normalized rows and per-row errors.
    """

    __tablename__ = "import_jobs"
    __table_args__ = (
        Index("ix_import_jobs_organization_id_created_at", "organization_id", "created_at"),
        # RAB item imports target one version; deleting the RAB removes its pending imports.
        ForeignKeyConstraint(
            ["organization_id", "rab_version_id"],
            ["rab_versions.organization_id", "rab_versions.id"],
            name="fk_import_jobs_rab_version_same_org",
            ondelete="CASCADE",
        ),
        Index("ix_import_jobs_rab_version_id", "rab_version_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(32))
    rab_version_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[ImportStatus] = mapped_column(str_enum(ImportStatus, "import_status"))
    filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int]
    row_count: Mapped[int]
    valid_count: Mapped[int]
    error_count: Mapped[int]
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
