from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.identity.models import User


class ApprovalAction(StrEnum):
    SUBMITTED = "submitted"
    WITHDRAWN = "withdrawn"
    APPROVED = "approved"
    REJECTED = "rejected"
    REOPENED = "reopened"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class ApprovalRecord(UUIDPrimaryKeyMixin, Base):
    """Append-only history of review decisions (who, when, from → to, note).

    Generic over `entity_type` so RAB versions now and issued documents later share one trail.
    """

    __tablename__ = "approval_records"
    __table_args__ = (
        Index("ix_approval_records_entity", "entity_type", "entity_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID]
    action: Mapped[ApprovalAction] = mapped_column(str_enum(ApprovalAction, "approval_action"))
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    actor: Mapped[User | None] = relationship(lazy="joined")
