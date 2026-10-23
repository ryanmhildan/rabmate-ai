"""source documents conversations

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20 18:27:19.807677

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate, then reviewed: enum CHECKs emitted once (explicitly named); CHECK changes on
    # the existing ai_runs table are written by hand (autogenerate cannot see them).
    op.create_table(
        "ai_conversations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_ai_conversations_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_ai_conversations_project_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ai_conversations_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversations")),
        sa.UniqueConstraint("organization_id", "id", name="uq_ai_conversations_organization_id_id"),
    )
    op.create_index(
        "ix_ai_conversations_owner",
        "ai_conversations",
        ["project_id", "created_by_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "source_documents",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "pdf",
                "xlsx",
                "csv",
                "image",
                name="source_kind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("extraction", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('pdf', 'xlsx', 'csv', 'image')", name=op.f("ck_source_documents_source_kind")
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_source_documents_sha256_hex")
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes = octet_length(content)",
            name=op.f("ck_source_documents_size_matches"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_source_documents_project_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_source_documents_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"], ["users.id"], name=op.f("fk_source_documents_uploaded_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_documents")),
        sa.UniqueConstraint("organization_id", "id", name="uq_source_documents_organization_id_id"),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "sha256",
            name=op.f("uq_source_documents_organization_id_project_id_sha256"),
        ),
    )
    op.create_index(
        "ix_source_documents_project_created",
        "source_documents",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "ai_messages",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                name="ai_message_role",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "sources", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name=op.f("ck_ai_messages_ai_message_role")
        ),
        sa.CheckConstraint("char_length(content) > 0", name=op.f("ck_ai_messages_content_present")),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["ai_conversations.organization_id", "ai_conversations.id"],
            name="fk_ai_messages_conversation_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ai_messages_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_runs.id"],
            name=op.f("fk_ai_messages_run_id_ai_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_messages")),
    )
    op.create_index(
        "ix_ai_messages_conversation_created",
        "ai_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.add_column("ai_runs", sa.Column("source_document_id", sa.Uuid(), nullable=True))
    op.add_column("ai_runs", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.alter_column("ai_runs", "rab_version_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        "ix_ai_runs_conversation_created",
        "ai_runs",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_ai_runs_source_document_same_org",
        "ai_runs",
        "source_documents",
        ["organization_id", "source_document_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_ai_runs_conversation_same_org",
        "ai_runs",
        "ai_conversations",
        ["organization_id", "conversation_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(op.f("ck_ai_runs_ai_run_kind"), "ai_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_runs_ai_run_kind"),
        "ai_runs",
        "kind IN ('rab_draft', 'extract_items', 'extract_document', 'chat_answer')",
    )
    op.create_check_constraint(
        op.f("ck_ai_runs_kind_target"),
        "ai_runs",
        "(kind IN ('rab_draft', 'extract_items') AND rab_version_id IS NOT NULL)"
        " OR (kind = 'extract_document' AND rab_version_id IS NOT NULL"
        " AND source_document_id IS NOT NULL)"
        " OR (kind = 'chat_answer' AND conversation_id IS NOT NULL)",
    )
    op.drop_constraint(op.f("ck_ai_runs_attempts_bounded"), "ai_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_runs_attempts_bounded"), "ai_runs", "attempts >= 0 AND attempts <= 100"
    )


def downgrade() -> None:
    # Runs of the new kinds cannot exist under the old schema (test-database round trips only).
    op.execute("DELETE FROM ai_runs WHERE kind IN ('extract_document', 'chat_answer')")
    op.execute("UPDATE ai_runs SET attempts = 5 WHERE attempts > 5")
    op.drop_constraint(op.f("ck_ai_runs_attempts_bounded"), "ai_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_runs_attempts_bounded"), "ai_runs", "attempts >= 0 AND attempts <= 5"
    )
    op.drop_constraint(op.f("ck_ai_runs_kind_target"), "ai_runs", type_="check")
    op.drop_constraint(op.f("ck_ai_runs_ai_run_kind"), "ai_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_runs_ai_run_kind"), "ai_runs", "kind IN ('rab_draft', 'extract_items')"
    )
    op.drop_constraint("fk_ai_runs_conversation_same_org", "ai_runs", type_="foreignkey")
    op.drop_constraint("fk_ai_runs_source_document_same_org", "ai_runs", type_="foreignkey")
    op.drop_index("ix_ai_runs_conversation_created", table_name="ai_runs")
    op.alter_column("ai_runs", "rab_version_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("ai_runs", "conversation_id")
    op.drop_column("ai_runs", "source_document_id")
    op.drop_index("ix_ai_messages_conversation_created", table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index("ix_source_documents_project_created", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index("ix_ai_conversations_owner", table_name="ai_conversations")
    op.drop_table("ai_conversations")
