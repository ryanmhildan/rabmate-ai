from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.numbering.models import DocumentSequence


def next_value(db: Session, organization_id: uuid.UUID, kind: str, year: int) -> int:
    """Atomically increments and returns the counter (row-level lock via upsert).

    Safe under concurrency: two transactions cannot obtain the same value. A rolled-back
    transaction leaves a gap, which is acceptable for document numbers.
    """
    stmt = (
        insert(DocumentSequence)
        .values(organization_id=organization_id, kind=kind, year=year, last_value=1)
        .on_conflict_do_update(
            index_elements=["organization_id", "kind", "year"],
            set_={"last_value": DocumentSequence.last_value + 1},
        )
        .returning(DocumentSequence.last_value)
    )
    return int(db.execute(stmt).scalar_one())


def format_number(prefix: str, year: int, value: int) -> str:
    return f"{prefix}-{year}-{value:04d}"
