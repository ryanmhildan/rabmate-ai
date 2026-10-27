"""document letterheads

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One active letterhead image per organization (ADR-048). Issued documents keep their own
    # stored PDFs, so replacing or deleting a row never changes an issued document.
    op.create_table(
        "document_letterheads",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes = octet_length(content)",
            name=op.f("ck_document_letterheads_size_matches"),
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_document_letterheads_sha256_hex")
        ),
        sa.CheckConstraint(
            "width_px > 0 AND height_px > 0",
            name=op.f("ck_document_letterheads_dimensions_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_document_letterheads_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_document_letterheads_uploaded_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_letterheads")),
        sa.UniqueConstraint(
            "organization_id", name=op.f("uq_document_letterheads_organization_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("document_letterheads")
