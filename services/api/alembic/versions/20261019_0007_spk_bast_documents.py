"""spk bast documents

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 12:56:03.171744

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate, then reviewed: enum CHECKs emitted once (explicitly named); the documents
    # doc_type CHECK and per-type source CHECKs are changed by hand (autogenerate cannot see them).
    op.create_table(
        "spk_documents",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "in_review",
                "approved",
                "rejected",
                "issued",
                "void",
                name="spk_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("quotation_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("contract_value", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("client_signatory_name", sa.String(length=200), nullable=True),
        sa.Column("client_signatory_title", sa.String(length=200), nullable=True),
        sa.Column("company_signatory_name", sa.String(length=200), nullable=True),
        sa.Column("company_signatory_title", sa.String(length=200), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_id", sa.Uuid(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(status = 'void') = (voided_at IS NOT NULL)",
            name=op.f("ck_spk_documents_void_timestamped"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'issued', 'void')",
            name=op.f("ck_spk_documents_spk_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('issued', 'void') OR (number IS NOT NULL AND issue_date IS NOT NULL)",
            name=op.f("ck_spk_documents_issued_has_number"),
        ),
        sa.CheckConstraint("contract_value >= 0", name=op.f("ck_spk_documents_value_non_negative")),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name=op.f("ck_spk_documents_period_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_spk_documents_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"], ["users.id"], name=op.f("fk_spk_documents_decided_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_spk_documents_client_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_spk_documents_project_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "quotation_id"],
            ["quotations.organization_id", "quotations.id"],
            name="fk_spk_documents_quotation_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_spk_documents_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"], ["users.id"], name=op.f("fk_spk_documents_submitted_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_id"], ["users.id"], name=op.f("fk_spk_documents_voided_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spk_documents")),
        sa.UniqueConstraint("organization_id", "id", name="uq_spk_documents_organization_id_id"),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_spk_documents_organization_id_number")
        ),
    )
    op.create_index(
        "uq_spk_documents_one_per_quotation",
        "spk_documents",
        ["quotation_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'void'"),
    )
    op.create_table(
        "bast_documents",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "in_review",
                "approved",
                "rejected",
                "issued",
                "void",
                name="bast_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "partial",
                "final",
                name="bast_kind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("spk_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("handover_date", sa.Date(), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("delivered_by_name", sa.String(length=200), nullable=True),
        sa.Column("delivered_by_title", sa.String(length=200), nullable=True),
        sa.Column("received_by_name", sa.String(length=200), nullable=True),
        sa.Column("received_by_title", sa.String(length=200), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_id", sa.Uuid(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(status = 'void') = (voided_at IS NOT NULL)",
            name=op.f("ck_bast_documents_void_timestamped"),
        ),
        sa.CheckConstraint(
            "kind IN ('partial', 'final')", name=op.f("ck_bast_documents_bast_kind")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'issued', 'void')",
            name=op.f("ck_bast_documents_bast_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('issued', 'void') OR (number IS NOT NULL AND handover_date IS NOT NULL)",
            name=op.f("ck_bast_documents_issued_has_number"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_bast_documents_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"], ["users.id"], name=op.f("fk_bast_documents_decided_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "spk_id"],
            ["spk_documents.organization_id", "spk_documents.id"],
            name="fk_bast_documents_spk_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_bast_documents_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"], ["users.id"], name=op.f("fk_bast_documents_submitted_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_id"], ["users.id"], name=op.f("fk_bast_documents_voided_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bast_documents")),
        sa.UniqueConstraint("organization_id", "id", name="uq_bast_documents_organization_id_id"),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_bast_documents_organization_id_number")
        ),
    )
    op.create_index("ix_bast_documents_spk_id", "bast_documents", ["spk_id"], unique=False)
    op.create_index(
        "uq_bast_documents_one_final_per_spk",
        "bast_documents",
        ["spk_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'final' AND status <> 'void'"),
    )
    op.create_table(
        "bast_items",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("bast_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("rab_item_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("condition", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_bast_items_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "bast_id"],
            ["bast_documents.organization_id", "bast_documents.id"],
            name="fk_bast_items_bast_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_bast_items_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["rab_item_id"], ["rab_items.id"], name=op.f("fk_bast_items_rab_item_id_rab_items")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bast_items")),
        sa.UniqueConstraint("bast_id", "position", name=op.f("uq_bast_items_bast_id_position")),
    )
    op.create_index("ix_bast_items_rab_item_id", "bast_items", ["rab_item_id"], unique=False)
    op.add_column("document_settings", sa.Column("spk_terms", sa.Text(), nullable=True))
    op.add_column("document_settings", sa.Column("bast_terms", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("spk_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("bast_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_documents_one_active_per_bast",
        "documents",
        ["bast_id"],
        unique=True,
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.create_index(
        "uq_documents_one_active_per_spk",
        "documents",
        ["spk_id"],
        unique=True,
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.create_foreign_key(
        "fk_documents_bast_same_org",
        "documents",
        "bast_documents",
        ["organization_id", "bast_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_documents_spk_same_org",
        "documents",
        "spk_documents",
        ["organization_id", "spk_id"],
        ["organization_id", "id"],
    )
    op.drop_constraint(op.f("ck_documents_document_type"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_document_type"),
        "documents",
        "doc_type IN ('rab', 'quotation', 'invoice', 'spk', 'bast')",
    )
    op.create_check_constraint(
        op.f("ck_documents_spk_needs_source"),
        "documents",
        "doc_type <> 'spk' OR spk_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_documents_bast_needs_source"),
        "documents",
        "doc_type <> 'bast' OR bast_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_documents_bast_needs_source"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_spk_needs_source"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_document_type"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_document_type"),
        "documents",
        "doc_type IN ('rab', 'quotation', 'invoice')",
    )
    op.drop_constraint("fk_documents_spk_same_org", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_bast_same_org", "documents", type_="foreignkey")
    op.drop_index(
        "uq_documents_one_active_per_spk",
        table_name="documents",
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.drop_index(
        "uq_documents_one_active_per_bast",
        table_name="documents",
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.drop_column("documents", "bast_id")
    op.drop_column("documents", "spk_id")
    op.drop_column("document_settings", "bast_terms")
    op.drop_column("document_settings", "spk_terms")
    op.drop_index("ix_bast_items_rab_item_id", table_name="bast_items")
    op.drop_table("bast_items")
    op.drop_index(
        "uq_bast_documents_one_final_per_spk",
        table_name="bast_documents",
        postgresql_where=sa.text("kind = 'final' AND status <> 'void'"),
    )
    op.drop_index("ix_bast_documents_spk_id", table_name="bast_documents")
    op.drop_table("bast_documents")
    op.drop_index(
        "uq_spk_documents_one_per_quotation",
        table_name="spk_documents",
        postgresql_where=sa.text("status <> 'void'"),
    )
    op.drop_table("spk_documents")
