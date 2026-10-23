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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.clients.models import Client
from app.modules.identity.models import User


class ProjectType(StrEnum):
    CONSTRUCTION = "construction"
    FABRICATION = "fabrication"
    PROCUREMENT = "procurement"
    IT = "it"
    PROFESSIONAL_SERVICES = "professional_services"
    OPERATIONS = "operations"
    OTHER = "other"


class ProjectStatus(StrEnum):
    PROSPECT = "prospect"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProjectMemberRole(StrEnum):
    LEAD = "lead"
    MEMBER = "member"


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        # Target for composite FKs (e.g. rab_documents) that must stay within one organization.
        UniqueConstraint("organization_id", "id", name="uq_projects_organization_id_id"),
        # A project can only point at a client of its own organization.
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_projects_client_same_org",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="dates_ordered",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint(
            "(tax_label IS NULL) = (tax_rate_percent IS NULL)", name="tax_label_and_rate"
        ),
        CheckConstraint(
            "tax_rate_percent IS NULL OR (tax_rate_percent >= 0 AND tax_rate_percent <= 100)",
            name="tax_rate_range",
        ),
        CheckConstraint("budget_amount IS NULL OR budget_amount >= 0", name="budget_non_negative"),
        Index("ix_projects_organization_id_status", "organization_id", "status"),
        Index("ix_projects_organization_id_created_at", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    number: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    project_type: Mapped[ProjectType] = mapped_column(str_enum(ProjectType, "project_type"))
    client_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(300))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ProjectStatus] = mapped_column(str_enum(ProjectStatus, "project_status"))
    currency: Mapped[str] = mapped_column(String(3), default="IDR", server_default="IDR")
    tax_label: Mapped[str | None] = mapped_column(String(32))
    tax_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    # Small, type-specific descriptive fields (e.g. building area for construction). Values that
    # must be searched, computed or audited belong in proper columns/tables instead.
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    client: Mapped[Client | None] = relationship(
        foreign_keys=[client_id],
        primaryjoin="Project.client_id == Client.id",
        viewonly=True,
        lazy="joined",
    )
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id], lazy="joined")
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProjectMember.created_at",
    )

    __mapper_args__ = {"version_id_col": version}


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[ProjectMemberRole] = mapped_column(
        str_enum(ProjectMemberRole, "project_member_role")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(lazy="joined")
