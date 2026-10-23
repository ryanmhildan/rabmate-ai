from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Stores a StrEnum as VARCHAR + CHECK constraint (no native PG enum: easier migrations)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )
