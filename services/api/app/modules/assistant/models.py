"""AI runs: one request to the local assistant, its status, and the draft it produced (ADR-041).

A run never changes business data by itself. Its `result` is a validated draft shown for review;
items reach a RAB only when a user applies them through `assistant.service.apply_run`, which goes
through the normal RAB rules. The run keeps the input and the data the assistant was given
(`context`) so users can see what a draft was based on; neither is ever written to logs.
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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import str_enum
from app.modules.identity.models import User


class AiRunKind(StrEnum):
    RAB_DRAFT = "rab_draft"  # items for a RAB from a work description
    EXTRACT_ITEMS = "extract_items"  # items read from pasted document text
    EXTRACT_DOCUMENT = "extract_document"  # items read from an uploaded file (ADR-043)
    CHAT_ANSWER = "chat_answer"  # one assistant answer in a project conversation (ADR-044)


# Kinds whose result is a list of items to review and apply to a RAB version.
ITEM_KINDS = (AiRunKind.RAB_DRAFT, AiRunKind.EXTRACT_ITEMS, AiRunKind.EXTRACT_DOCUMENT)


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class AiRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    APPLIED = "applied"
    DISCARDED = "discarded"


ACTIVE_STATUSES = (AiRunStatus.QUEUED, AiRunStatus.RUNNING)


class AiRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "rab_version_id"],
            ["rab_versions.organization_id", "rab_versions.id"],
            name="fk_ai_runs_rab_version_same_org",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_document_id"],
            ["source_documents.organization_id", "source_documents.id"],
            name="fk_ai_runs_source_document_same_org",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["ai_conversations.organization_id", "ai_conversations.id"],
            name="fk_ai_runs_conversation_same_org",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(kind IN ('rab_draft', 'extract_items') AND rab_version_id IS NOT NULL)"
            " OR (kind = 'extract_document' AND rab_version_id IS NOT NULL"
            " AND source_document_id IS NOT NULL)"
            " OR (kind = 'chat_answer' AND conversation_id IS NOT NULL)",
            name="kind_target",
        ),
        # The local model serves one request at a time: one active run per organization.
        Index(
            "uq_ai_runs_one_active_per_org",
            "organization_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_ai_runs_rab_version_created", "rab_version_id", "created_at"),
        Index("ix_ai_runs_conversation_created", "conversation_id", "created_at"),
        CheckConstraint("(status = 'applied') = (applied_at IS NOT NULL)", name="applied_dated"),
        # Model calls per run (chunked document extraction makes several, each with a retry).
        CheckConstraint("attempts >= 0 AND attempts <= 100", name="attempts_bounded"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    rab_version_id: Mapped[uuid.UUID | None] = mapped_column()
    source_document_id: Mapped[uuid.UUID | None] = mapped_column()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[AiRunKind] = mapped_column(str_enum(AiRunKind, "ai_run_kind"))
    status: Mapped[AiRunStatus] = mapped_column(str_enum(AiRunStatus, "ai_run_status"))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    applied_count: Mapped[int | None] = mapped_column()
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")


class AiConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project-scoped chat with the assistant; private to the user who started it (ADR-044)."""

    __tablename__ = "ai_conversations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_ai_conversations_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_ai_conversations_project_same_org",
            ondelete="CASCADE",
        ),
        Index("ix_ai_conversations_owner", "project_id", "created_by_id", "updated_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    project_id: Mapped[uuid.UUID] = mapped_column()
    title: Mapped[str] = mapped_column(String(200))
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class AiMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["ai_conversations.organization_id", "ai_conversations.id"],
            name="fk_ai_messages_conversation_same_org",
            ondelete="CASCADE",
        ),
        Index("ix_ai_messages_conversation_created", "conversation_id", "created_at"),
        CheckConstraint("char_length(content) > 0", name="content_present"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column()
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole, "ai_message_role"))
    content: Mapped[str] = mapped_column(Text)
    # Assistant answers: the sources actually cited, and checks that flagged something.
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_runs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
