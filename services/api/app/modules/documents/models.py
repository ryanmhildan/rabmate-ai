from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.identity.models import User

DEFAULT_ACCENT_COLOR = "#1F4E79"


class DocumentType(StrEnum):
    RAB = "rab"
    QUOTATION = "quotation"
    INVOICE = "invoice"
    SPK = "spk"
    BAST = "bast"


class DocumentStatus(StrEnum):
    ISSUED = "issued"
    VOID = "void"


class FileFormat(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"


class DocumentSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-organization document template: letterhead extras, terms, layout options, payment info.

    Company identity (name, address, NPWP, contacts) is read from the organization profile; nothing
    here is invented when a field is empty — the document simply omits it.
    """

    __tablename__ = "document_settings"
    __table_args__ = (
        CheckConstraint("accent_color ~ '^#[0-9A-Fa-f]{6}$'", name="accent_color_hex"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), unique=True)
    tagline: Mapped[str | None] = mapped_column(String(200))
    accent_color: Mapped[str] = mapped_column(String(7), default=DEFAULT_ACCENT_COLOR)
    footer_text: Mapped[str | None] = mapped_column(String(500))
    rab_terms: Mapped[str | None] = mapped_column(Text)
    show_item_codes: Mapped[bool] = mapped_column(default=True, server_default=true())
    show_price_sources: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    show_amount_in_words: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Used by invoices (Phase 6); configured together with the rest of the template.
    payment_bank_name: Mapped[str | None] = mapped_column(String(100))
    payment_account_number: Mapped[str | None] = mapped_column(String(50))
    payment_account_holder: Mapped[str | None] = mapped_column(String(200))
    # Default terms copied into new SPK / BAST drafts; written by the organization, never generated.
    spk_terms: Mapped[str | None] = mapped_column(Text)
    bast_terms: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


class IssuedDocument(UUIDPrimaryKeyMixin, Base):
    """An issued business document: frozen snapshot + rendered files. Immutable except voiding."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "id", name="uq_documents_organization_id_id"),
        # Retrying an issue request with the same key returns the same document.
        UniqueConstraint("organization_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["organization_id", "rab_version_id"],
            ["rab_versions.organization_id", "rab_versions.id"],
            name="fk_documents_rab_version_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_documents_project_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "quotation_id"],
            ["quotations.organization_id", "quotations.id"],
            name="fk_documents_quotation_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_documents_invoice_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "spk_id"],
            ["spk_documents.organization_id", "spk_documents.id"],
            name="fk_documents_spk_same_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "bast_id"],
            ["bast_documents.organization_id", "bast_documents.id"],
            name="fk_documents_bast_same_org",
        ),
        # At most one valid (non-void) document per source.
        Index(
            "uq_documents_one_active_per_rab_version",
            "rab_version_id",
            unique=True,
            postgresql_where=text("status = 'issued'"),
        ),
        Index(
            "uq_documents_one_active_per_quotation",
            "quotation_id",
            unique=True,
            postgresql_where=text("status = 'issued'"),
        ),
        Index(
            "uq_documents_one_active_per_invoice",
            "invoice_id",
            unique=True,
            postgresql_where=text("status = 'issued'"),
        ),
        Index(
            "uq_documents_one_active_per_spk",
            "spk_id",
            unique=True,
            postgresql_where=text("status = 'issued'"),
        ),
        Index(
            "uq_documents_one_active_per_bast",
            "bast_id",
            unique=True,
            postgresql_where=text("status = 'issued'"),
        ),
        Index("ix_documents_organization_id_issued_at", "organization_id", "issued_at"),
        CheckConstraint(
            "doc_type <> 'rab' OR rab_version_id IS NOT NULL", name="rab_needs_version"
        ),
        CheckConstraint(
            "doc_type <> 'quotation' OR quotation_id IS NOT NULL", name="quotation_needs_source"
        ),
        CheckConstraint(
            "doc_type <> 'invoice' OR invoice_id IS NOT NULL", name="invoice_needs_source"
        ),
        CheckConstraint("doc_type <> 'spk' OR spk_id IS NOT NULL", name="spk_needs_source"),
        CheckConstraint("doc_type <> 'bast' OR bast_id IS NOT NULL", name="bast_needs_source"),
        CheckConstraint("(status = 'void') = (voided_at IS NOT NULL)", name="void_timestamped"),
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    doc_type: Mapped[DocumentType] = mapped_column(str_enum(DocumentType, "document_type"))
    status: Mapped[DocumentStatus] = mapped_column(str_enum(DocumentStatus, "document_status"))
    number: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    project_id: Mapped[uuid.UUID | None] = mapped_column()
    rab_version_id: Mapped[uuid.UUID | None] = mapped_column()
    quotation_id: Mapped[uuid.UUID | None] = mapped_column()
    invoice_id: Mapped[uuid.UUID | None] = mapped_column()
    spk_id: Mapped[uuid.UUID | None] = mapped_column()
    bast_id: Mapped[uuid.UUID | None] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    schema_version: Mapped[int]
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, deferred=True)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    issued_by: Mapped[User | None] = relationship(foreign_keys=[issued_by_id], lazy="joined")
    voided_by: Mapped[User | None] = relationship(foreign_keys=[voided_by_id], lazy="joined")
    files: Mapped[list[DocumentFile]] = relationship(
        back_populates="document", order_by="DocumentFile.format", lazy="selectin"
    )


class DocumentFile(UUIDPrimaryKeyMixin, Base):
    """A rendering of an issued document, stored once at issuance (bounded size, in PostgreSQL)."""

    __tablename__ = "document_files"
    __table_args__ = (
        UniqueConstraint("document_id", "format"),
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["documents.organization_id", "documents.id"],
            name="fk_document_files_document_same_org",
            ondelete="CASCADE",
        ),
        CheckConstraint("size_bytes = octet_length(content)", name="size_matches_content"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    document_id: Mapped[uuid.UUID] = mapped_column()
    format: Mapped[FileFormat] = mapped_column(str_enum(FileFormat, "document_file_format"))
    content_type: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    document: Mapped[IssuedDocument] = relationship(back_populates="files")
