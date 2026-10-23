"""Item-level comparison between two RAB versions. Pure.

Items are matched by code when present, otherwise by name + unit (case-insensitive). Repeated
keys inside one version are disambiguated by occurrence order so matching stays deterministic.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class CompareItem:
    code: str | None
    name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal | None
    subtotal: Decimal | None
    item_type: str
    specification: str | None = None


@dataclass(frozen=True)
class ItemChange:
    key: str
    kind: ChangeKind
    before: CompareItem | None
    after: CompareItem | None
    changed_fields: list[str] = field(default_factory=list)

    @property
    def current(self) -> CompareItem:
        """The item as it is now (or as it was, for removed items)."""
        item = self.after or self.before
        if item is None:
            raise ValueError("ItemChange without items")
        return item

    @property
    def subtotal_delta(self) -> Decimal:
        before = (self.before.subtotal if self.before else None) or Decimal("0.00")
        after = (self.after.subtotal if self.after else None) or Decimal("0.00")
        return after - before


_COMPARED_FIELDS = ("name", "unit", "quantity", "unit_price", "item_type", "specification")


def _base_key(item: CompareItem) -> str:
    if item.code and item.code.strip():
        return f"code:{item.code.strip().lower()}"
    return f"name:{item.name.strip().lower()}|{item.unit.strip().lower()}"


def _keyed(items: Sequence[CompareItem]) -> dict[str, CompareItem]:
    seen: defaultdict[str, int] = defaultdict(int)
    keyed: dict[str, CompareItem] = {}
    for item in items:
        base = _base_key(item)
        seen[base] += 1
        keyed[base if seen[base] == 1 else f"{base}#{seen[base]}"] = item
    return keyed


def compare_items(before: Sequence[CompareItem], after: Sequence[CompareItem]) -> list[ItemChange]:
    old, new = _keyed(before), _keyed(after)
    changes: list[ItemChange] = []
    # Order: everything in the new version (its order), then removed items (old order).
    for key, item in new.items():
        previous = old.get(key)
        if previous is None:
            changes.append(ItemChange(key, ChangeKind.ADDED, None, item))
            continue
        fields = [f for f in _COMPARED_FIELDS if getattr(previous, f) != getattr(item, f)]
        kind = ChangeKind.CHANGED if fields else ChangeKind.UNCHANGED
        changes.append(ItemChange(key, kind, previous, item, fields))
    for key, item in old.items():
        if key not in new:
            changes.append(ItemChange(key, ChangeKind.REMOVED, item, None))
    return changes
