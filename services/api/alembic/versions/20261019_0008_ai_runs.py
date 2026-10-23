"""ai runs

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19 15:00:33.567661

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate, then reviewed: enum CHECKs emitted once (explicitly named).
    op.create_table(
        "ai_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("rab_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "rab_draft",
                "extract_items",
                name="ai_run_kind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "applied",
                "discarded",
                name="ai_run_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by_id", sa.Uuid(), nullable=True),
        sa.Column("applied_count", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "(status = 'applied') = (applied_at IS NOT NULL)", name=op.f("ck_ai_runs_applied_dated")
        ),
        sa.CheckConstraint(
            "kind IN ('rab_draft', 'extract_items')", name=op.f("ck_ai_runs_ai_run_kind")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'applied', 'discarded')",
            name=op.f("ck_ai_runs_ai_run_status"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 5", name=op.f("ck_ai_runs_attempts_bounded")
        ),
        sa.ForeignKeyConstraint(
            ["applied_by_id"], ["users.id"], name=op.f("fk_ai_runs_applied_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_ai_runs_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "rab_version_id"],
            ["rab_versions.organization_id", "rab_versions.id"],
            name="fk_ai_runs_rab_version_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ai_runs_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_runs")),
    )
    op.create_index(
        "ix_ai_runs_rab_version_created", "ai_runs", ["rab_version_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_ai_runs_one_active_per_org",
        "ai_runs",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ai_runs_one_active_per_org",
        table_name="ai_runs",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_index("ix_ai_runs_rab_version_created", table_name="ai_runs")
    op.drop_table("ai_runs")
