"""Uploaded source documents (PDF, spreadsheets, images) for AI extraction (ADR-043).

The original bytes are stored once (PostgreSQL bytea, like issued document files) and identified
by SHA-256; uploading the same file to the same project again returns the stored copy. The text
read from it (per page or sheet, with the method used: text layer, table cells, OCR) is cached in
`extraction` after the first run so later runs do not parse or OCR it again.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.identity.models import User


class SourceKind(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"
    CSV = "csv"
    IMAGE = "image"


class SourceDocument(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_source_documents_organization_id_id"),
        # The same file uploaded twice to one project is one document.
        UniqueConstraint("organization_id", "project_id", "sha256"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_source_documents_project_same_org",
            ondelete="CASCADE",
        ),
        Index("ix_source_documents_project_created", "project_id", "created_at"),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes = octet_length(content)", name="size_matches"
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    project_id: Mapped[uuid.UUID] = mapped_column()
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind, "source_kind"))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    # {"pages": [{"no", "label", "method", "lines": [...]}], "warnings": [...], "ocr": {...}}
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB, deferred=True)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id], lazy="joined")
