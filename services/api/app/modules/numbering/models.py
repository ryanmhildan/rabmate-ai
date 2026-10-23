from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentSequence(Base):
    """Per-organization, per-kind, per-year counter for human-readable document numbers."""

    __tablename__ = "document_sequences"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    year: Mapped[int] = mapped_column(primary_key=True)
    last_value: Mapped[int] = mapped_column(default=0)
