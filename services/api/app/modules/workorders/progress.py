"""Contract items of an SPK and the volumes handed over against them (ADR-039).

The contract is the RAB version the accepted quotation was made from (approved, immutable).
"Delivered" counts only issued BASTs; drafts and BASTs under review are "pending" — they are not
yet a handover. The rule enforced on save, submit and issue: for every contract item, delivered
(other issued BASTs) + this BAST <= contract volume. Issuance re-checks it while holding the SPK
row lock, so two BASTs cannot be issued past the contract concurrently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import BusinessValidationError
from app.modules.billing.models import DocStatus
from app.modules.documents import formatting as fmt
from app.modules.rab.models import RabItem
from app.modules.workorders.models import Bast, BastItem, Spk

ZERO = Decimal("0")
PENDING = (DocStatus.DRAFT, DocStatus.IN_REVIEW, DocStatus.APPROVED)


@dataclass(frozen=True)
class ContractItem:
    no: int
    item: RabItem


def contract_items(db: Session, ctx: RequestContext, spk: Spk) -> dict[uuid.UUID, ContractItem]:
    """Contract items by id, numbered like the quotation/RAB (by position)."""
    rows = (
        db.execute(
            select(RabItem)
            .where(
                RabItem.version_id == spk.quotation.rab_version_id,
                RabItem.organization_id == ctx.organization_id,
            )
            .order_by(RabItem.position)
        )
        .scalars()
        .all()
    )
    return {item.id: ContractItem(no, item) for no, item in enumerate(rows, start=1)}


def handed_over(
    db: Session,
    ctx: RequestContext,
    spk_id: uuid.UUID,
    statuses: tuple[DocStatus, ...],
    *,
    exclude_bast_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, Decimal]:
    """Sum of BAST quantities per contract item for BASTs of `spk_id` in `statuses`."""
    stmt = (
        select(BastItem.rab_item_id, func.sum(BastItem.quantity))
        .join(Bast, Bast.id == BastItem.bast_id)
        .where(
            Bast.spk_id == spk_id,
            Bast.organization_id == ctx.organization_id,
            Bast.status.in_(statuses),
            BastItem.rab_item_id.is_not(None),
        )
        .group_by(BastItem.rab_item_id)
    )
    if exclude_bast_id is not None:
        stmt = stmt.where(Bast.id != exclude_bast_id)
    return {item_id: total for item_id, total in db.execute(stmt) if item_id is not None}


@dataclass(frozen=True)
class ItemProgress:
    no: int
    item: RabItem
    delivered: Decimal
    pending: Decimal

    @property
    def remaining(self) -> Decimal:
        return max(self.item.quantity - self.delivered, ZERO)


def progress(db: Session, ctx: RequestContext, spk: Spk) -> list[ItemProgress]:
    delivered = handed_over(db, ctx, spk.id, (DocStatus.ISSUED,))
    pending = handed_over(db, ctx, spk.id, PENDING)
    return [
        ItemProgress(c.no, c.item, delivered.get(item_id, ZERO), pending.get(item_id, ZERO))
        for item_id, c in contract_items(db, ctx, spk).items()
    ]


def check_lines(
    db: Session,
    ctx: RequestContext,
    spk: Spk,
    bast_id: uuid.UUID | None,
    lines: list[tuple[uuid.UUID | None, Decimal, str]],
) -> None:
    """Validates (rab_item_id, quantity, unit) lines against the contract; raises with locations."""
    contract = contract_items(db, ctx, spk)
    delivered = handed_over(db, ctx, spk.id, (DocStatus.ISSUED,), exclude_bast_id=bast_id)
    seen: set[uuid.UUID] = set()
    errors: list[dict[str, object]] = []
    for index, (rab_item_id, quantity, unit) in enumerate(lines):
        if rab_item_id is None:
            continue
        c = contract.get(rab_item_id)
        if c is None:
            errors.append(
                {
                    "loc": ["body", "items", index, "rab_item_id"],
                    "msg": "Item bukan bagian dari kontrak SPK ini.",
                }
            )
            continue
        if rab_item_id in seen:
            errors.append(
                {
                    "loc": ["body", "items", index, "rab_item_id"],
                    "msg": "Item kontrak ini sudah ada di baris lain.",
                }
            )
            continue
        seen.add(rab_item_id)
        if unit != c.item.unit:
            errors.append(
                {
                    "loc": ["body", "items", index, "unit"],
                    "msg": f"Satuan harus sama dengan kontrak ({c.item.unit}).",
                }
            )
        available = c.item.quantity - delivered.get(rab_item_id, ZERO)
        if quantity > available:
            errors.append(
                {
                    "loc": ["body", "items", index, "quantity"],
                    "msg": f"Melebihi sisa volume kontrak ({fmt.quantity(max(available, ZERO))} "
                    f"{c.item.unit}).",
                }
            )
    if errors:
        raise BusinessValidationError(
            "Volume serah terima tidak sesuai dengan kontrak.", details=errors
        )
