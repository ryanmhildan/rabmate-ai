from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import QueryableAttribute, Session

from app.core.errors import BusinessValidationError


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1, le=10_000, description="Halaman, mulai dari 1"),
    page_size: int = Query(20, ge=1, le=100, description="Jumlah item per halaman (maks. 100)"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def apply_sort[S: Select[*tuple[Any, ...]]](
    stmt: S,
    sort: str | None,
    allowed: Mapping[str, QueryableAttribute[Any]],
    default: str,
) -> S:
    """`sort=name` ascending, `sort=-name` descending; only whitelisted keys are accepted."""
    key = sort or default
    descending = key.startswith("-")
    column = allowed.get(key.lstrip("-"))
    if column is None:
        raise BusinessValidationError(
            "Parameter sort tidak dikenal.", details={"allowed": sorted(allowed)}
        )
    return stmt.order_by(column.desc() if descending else column.asc())


def count_rows(db: Session, stmt: Select[*tuple[Any, ...]]) -> int:
    return int(
        db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    )


def paginate(db: Session, stmt: Select[Any], params: PageParams) -> tuple[list[Any], int]:
    total = count_rows(db, stmt)
    rows = db.execute(stmt.limit(params.page_size).offset(params.offset)).unique().scalars().all()
    return list(rows), total


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
