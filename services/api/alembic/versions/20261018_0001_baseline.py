"""baseline: empty schema, establishes the Alembic version table

Revision ID: 0001
Revises:
Create Date: 2026-10-18

"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Business tables arrive in Phase 2 (organizations, users, roles, clients, projects).
    pass


def downgrade() -> None:
    pass
