"""quotations terms invoices payments

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 09:50:31.020586

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate, then reviewed: enum CHECKs emitted once (explicitly named); the documents
    # doc_type CHECK and per-type source CHECKs are added by hand (autogenerate cannot see them).
    op.create_table(
        "payments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "transfer",
                "cash",
                "cheque",
                "giro",
                "other",
                name="payment_method",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "recorded",
                "void",
                name="payment_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_id", sa.Uuid(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'void') = (voided_at IS NOT NULL)", name=op.f("ck_payments_void_timestamped")
        ),
        sa.CheckConstraint(
            "method IN ('transfer', 'cash', 'cheque', 'giro', 'other')",
            name=op.f("ck_payments_payment_method"),
        ),
        sa.CheckConstraint(
            "status IN ('recorded', 'void')", name=op.f("ck_payments_payment_status")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_payments_client_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_payments_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"], ["users.id"], name=op.f("fk_payments_recorded_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_id"], ["users.id"], name=op.f("fk_payments_voided_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("organization_id", "id", name="uq_payments_organization_id_id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name=op.f("uq_payments_organization_id_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_payments_organization_id_payment_date",
        "payments",
        ["organization_id", "payment_date"],
        unique=False,
    )
    op.create_table(
        "quotations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("rab_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "in_review",
                "approved",
                "rejected",
                "issued",
                "void",
                name="quotation_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("introduction", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("taxable_base", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("tax_label", sa.String(length=32), nullable=True),
        sa.Column("tax_rate_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("grand_total", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column(
            "client_response",
            sa.Enum(
                "accepted",
                "declined",
                name="client_response",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_note", sa.Text(), nullable=True),
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
            name=op.f("ck_quotations_void_timestamped"),
        ),
        sa.CheckConstraint(
            "client_response IN ('accepted', 'declined')",
            name=op.f("ck_quotations_client_response"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'issued', 'void')",
            name=op.f("ck_quotations_quotation_status"),
        ),
        sa.CheckConstraint(
            "(client_response IS NULL) = (responded_at IS NULL)",
            name=op.f("ck_quotations_response_timestamped"),
        ),
        sa.CheckConstraint(
            "grand_total = taxable_base + tax_amount", name=op.f("ck_quotations_total_consistent")
        ),
        sa.CheckConstraint(
            "grand_total >= 0 AND taxable_base >= 0 AND tax_amount >= 0",
            name=op.f("ck_quotations_amounts_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_quotations_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"], ["users.id"], name=op.f("fk_quotations_decided_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_quotations_project_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "rab_version_id"],
            ["rab_versions.organization_id", "rab_versions.id"],
            name="fk_quotations_rab_version_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_quotations_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"], ["users.id"], name=op.f("fk_quotations_submitted_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_id"], ["users.id"], name=op.f("fk_quotations_voided_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotations")),
        sa.UniqueConstraint("organization_id", "id", name="uq_quotations_organization_id_id"),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_quotations_organization_id_number")
        ),
    )
    op.create_index(
        "ix_quotations_organization_id_created_at",
        "quotations",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "payment_terms",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("quotation_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "basis",
            sa.Enum(
                "percent",
                "amount",
                name="term_basis",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(basis = 'percent') = (percent IS NOT NULL)",
            name=op.f("ck_payment_terms_percent_matches_basis"),
        ),
        sa.CheckConstraint(
            "basis IN ('percent', 'amount')", name=op.f("ck_payment_terms_term_basis")
        ),
        sa.CheckConstraint(
            "amount >= 0 AND tax_amount >= 0", name=op.f("ck_payment_terms_amounts_non_negative")
        ),
        sa.CheckConstraint(
            "percent IS NULL OR (percent > 0 AND percent <= 100)",
            name=op.f("ck_payment_terms_percent_range"),
        ),
        sa.CheckConstraint(
            "total_amount = amount + tax_amount", name=op.f("ck_payment_terms_total_consistent")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "quotation_id"],
            ["quotations.organization_id", "quotations.id"],
            name="fk_payment_terms_quotation_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_payment_terms_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_terms")),
        sa.UniqueConstraint("organization_id", "id", name="uq_payment_terms_organization_id_id"),
        sa.UniqueConstraint(
            "quotation_id", "position", name=op.f("uq_payment_terms_quotation_id_position")
        ),
    )
    op.create_table(
        "invoices",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "term",
                "manual",
                name="invoice_kind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "in_review",
                "approved",
                "rejected",
                "issued",
                "void",
                name="invoice_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("quotation_id", sa.Uuid(), nullable=True),
        sa.Column("payment_term_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("tax_label", sa.String(length=32), nullable=True),
        sa.Column("tax_rate_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("grand_total", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column(
            "amount_paid", sa.Numeric(precision=20, scale=2), server_default="0", nullable=False
        ),
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
            "(kind = 'term') = (payment_term_id IS NOT NULL)",
            name=op.f("ck_invoices_term_invoice_has_term"),
        ),
        sa.CheckConstraint(
            "(status = 'void') = (voided_at IS NOT NULL)", name=op.f("ck_invoices_void_timestamped")
        ),
        sa.CheckConstraint("kind IN ('term', 'manual')", name=op.f("ck_invoices_invoice_kind")),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'issued', 'void')",
            name=op.f("ck_invoices_invoice_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('issued', 'void') OR (number IS NOT NULL AND issue_date IS NOT NULL AND due_date IS NOT NULL)",
            name=op.f("ck_invoices_issued_has_number_and_dates"),
        ),
        sa.CheckConstraint(
            "amount_paid >= 0 AND amount_paid <= grand_total",
            name=op.f("ck_invoices_paid_within_total"),
        ),
        sa.CheckConstraint(
            "due_date IS NULL OR issue_date IS NULL OR due_date >= issue_date",
            name=op.f("ck_invoices_due_after_issue"),
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND tax_amount >= 0 AND grand_total = subtotal + tax_amount",
            name=op.f("ck_invoices_totals_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_invoices_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"], ["users.id"], name=op.f("fk_invoices_decided_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_invoices_client_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "payment_term_id"],
            ["payment_terms.organization_id", "payment_terms.id"],
            name="fk_invoices_payment_term_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_invoices_project_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "quotation_id"],
            ["quotations.organization_id", "quotations.id"],
            name="fk_invoices_quotation_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invoices_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"], ["users.id"], name=op.f("fk_invoices_submitted_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_id"], ["users.id"], name=op.f("fk_invoices_voided_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("organization_id", "id", name="uq_invoices_organization_id_id"),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_invoices_organization_id_number")
        ),
    )
    op.create_index(
        "ix_invoices_organization_id_due_date",
        "invoices",
        ["organization_id", "due_date"],
        unique=False,
    )
    op.create_index(
        "uq_invoices_one_per_payment_term",
        "invoices",
        ["payment_term_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'void'"),
    )
    op.create_table(
        "invoice_items",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_invoice_items_quantity_positive")),
        sa.CheckConstraint(
            "unit_price >= 0 AND amount >= 0", name=op.f("ck_invoice_items_amounts_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_invoice_items_invoice_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invoice_items_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_items")),
        sa.UniqueConstraint(
            "invoice_id", "position", name=op.f("uq_invoice_items_invoice_id_position")
        ),
    )
    op.create_table(
        "payment_allocations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payment_allocations_amount_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_payment_allocations_invoice_same_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "payment_id"],
            ["payments.organization_id", "payments.id"],
            name="fk_payment_allocations_payment_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_payment_allocations_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_allocations")),
        sa.UniqueConstraint(
            "payment_id", "invoice_id", name=op.f("uq_payment_allocations_payment_id_invoice_id")
        ),
    )
    op.create_index(
        "ix_payment_allocations_invoice_id", "payment_allocations", ["invoice_id"], unique=False
    )
    op.add_column("documents", sa.Column("quotation_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("invoice_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_documents_one_active_per_invoice",
        "documents",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.create_index(
        "uq_documents_one_active_per_quotation",
        "documents",
        ["quotation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.create_foreign_key(
        "fk_documents_invoice_same_org",
        "documents",
        "invoices",
        ["organization_id", "invoice_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_documents_quotation_same_org",
        "documents",
        "quotations",
        ["organization_id", "quotation_id"],
        ["organization_id", "id"],
    )
    op.drop_constraint(op.f("ck_documents_document_type"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_document_type"),
        "documents",
        "doc_type IN ('rab', 'quotation', 'invoice')",
    )
    op.create_check_constraint(
        op.f("ck_documents_quotation_needs_source"),
        "documents",
        "doc_type <> 'quotation' OR quotation_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_documents_invoice_needs_source"),
        "documents",
        "doc_type <> 'invoice' OR invoice_id IS NOT NULL",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_constraint(op.f("ck_documents_invoice_needs_source"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_quotation_needs_source"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_document_type"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_document_type"), "documents", "doc_type IN ('rab')"
    )
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("fk_documents_quotation_same_org", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_invoice_same_org", "documents", type_="foreignkey")
    op.drop_index(
        "uq_documents_one_active_per_quotation",
        table_name="documents",
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.drop_index(
        "uq_documents_one_active_per_invoice",
        table_name="documents",
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.drop_column("documents", "invoice_id")
    op.drop_column("documents", "quotation_id")
    op.drop_index("ix_payment_allocations_invoice_id", table_name="payment_allocations")
    op.drop_table("payment_allocations")
    op.drop_table("invoice_items")
    op.drop_index(
        "uq_invoices_one_per_payment_term",
        table_name="invoices",
        postgresql_where=sa.text("status <> 'void'"),
    )
    op.drop_index("ix_invoices_organization_id_due_date", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("payment_terms")
    op.drop_index("ix_quotations_organization_id_created_at", table_name="quotations")
    op.drop_table("quotations")
    op.drop_index("ix_payments_organization_id_payment_date", table_name="payments")
    op.drop_table("payments")
    # ### end Alembic commands ###
