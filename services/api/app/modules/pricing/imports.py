"""Price import workflow: upload → preview (stored) → explicit commit. Org-scoped."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.modules.audit import service as audit
from app.modules.pricing import schemas
from app.modules.pricing.importer import ImportFileError, parse_file
from app.modules.pricing.models import (
    ImportJob,
    ImportStatus,
    ObservationSource,
    PriceCatalogItem,
    Supplier,
)
from app.modules.pricing.service import _new_observation
from app.modules.pricing.units import same_unit
from app.modules.rab.models import RabItemType

KIND = "price_catalog"


def safe_filename(raw: str | None) -> str:
    """Display-only name: no path, no control characters."""
    name = (raw or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    return name.strip()[:255] or "upload"


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _find_item(db: Session, ctx: RequestContext, data: dict[str, Any]) -> PriceCatalogItem | None:
    base = select(PriceCatalogItem).where(PriceCatalogItem.organization_id == ctx.organization_id)
    if data.get("code"):
        return db.execute(
            base.where(func.lower(PriceCatalogItem.code) == data["code"].lower())
        ).scalar_one_or_none()
    # Without a code only an exact description match counts as "the same item":
    # similar names are never merged (different spec/brand/unit = different item).
    for item in db.execute(
        base.where(func.lower(PriceCatalogItem.name) == _norm(data["name"]))
    ).scalars():
        if (
            _norm(item.brand) == _norm(data.get("brand"))
            and _norm(item.specification) == _norm(data.get("specification"))
            and same_unit(item.unit, data["unit"])
        ):
            return item
    return None


def _plan(db: Session, ctx: RequestContext, row: dict[str, Any]) -> None:
    """Annotates a valid row with the action commit would take (or turns it into an error)."""
    data = row["data"]
    item = _find_item(db, ctx, data)
    if item is None:
        row["action"] = "create_item"
        return
    if not same_unit(item.unit, data["unit"]):
        row["valid"] = False
        row["errors"].append(
            f"Kode {data['code']} sudah dipakai item dengan satuan {item.unit}; satuan berbeda."
        )
        row["action"] = None
        return
    row["action"] = "add_price"
    row["catalog_item_id"] = str(item.id)


def preview(db: Session, ctx: RequestContext, filename: str, content: bytes) -> ImportJob:
    try:
        parsed = parse_file(filename, content)
    except ImportFileError as exc:
        raise BusinessValidationError(str(exc)) from None
    rows: list[dict[str, Any]] = []
    for result in parsed.rows:
        row: dict[str, Any] = {
            "row": result.row,
            "valid": result.valid,
            "errors": list(result.errors),
            "data": result.data,
            "action": None,
        }
        if result.valid:
            _plan(db, ctx, row)
        rows.append(row)
    valid = sum(1 for r in rows if r["valid"])
    job = ImportJob(
        organization_id=ctx.organization_id,
        kind=KIND,
        status=ImportStatus.PREVIEWED,
        filename=filename,
        file_size=len(content),
        row_count=len(rows),
        valid_count=valid,
        error_count=len(rows) - valid,
        rows=rows,
        warnings=parsed.warnings,
        created_by_id=ctx.user_id,
    )
    db.add(job)
    db.commit()
    return job


def get_job(
    db: Session, ctx: RequestContext, job_id: uuid.UUID, *, lock: bool = False
) -> ImportJob:
    stmt = select(ImportJob).where(
        ImportJob.id == job_id,
        ImportJob.organization_id == ctx.organization_id,
        ImportJob.kind == KIND,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise NotFoundError("Data impor tidak ditemukan.")
    return job


def commit(db: Session, ctx: RequestContext, job_id: uuid.UUID) -> ImportJob:
    job = get_job(db, ctx, job_id, lock=True)
    if job.status is ImportStatus.COMMITTED:
        return job  # idempotent: a retried request must not import twice
    if job.status is ImportStatus.DISCARDED:
        raise ConflictError("Impor ini sudah dibatalkan.")
    if job.valid_count == 0:
        raise BusinessValidationError("Tidak ada baris valid untuk disimpan.")

    items_by_key: dict[str, PriceCatalogItem] = {}
    suppliers: dict[str, Supplier] = {}
    created_items = created_suppliers = created_prices = 0

    for row in job.rows:
        if not row["valid"]:
            continue
        data = row["data"]
        # Re-resolve: the catalog may have changed since the preview.
        key = (data.get("code") or "").lower() or "|".join(
            _norm(data.get(k)) for k in ("name", "brand", "specification", "unit")
        )
        item = items_by_key.get(key) or _find_item(db, ctx, data)
        if item is not None and not same_unit(item.unit, data["unit"]):
            row["valid"] = False
            row["errors"].append(f"Satuan berbeda dengan item katalog ({item.unit}); dilewati.")
            continue
        if item is None:
            item = PriceCatalogItem(
                organization_id=ctx.organization_id,
                code=data.get("code"),
                name=data["name"],
                category=data.get("category"),
                brand=data.get("brand"),
                specification=data.get("specification"),
                unit=data["unit"],
                item_type=RabItemType(data["item_type"]),
                created_by_id=ctx.user_id,
            )
            db.add(item)
            db.flush()
            created_items += 1
        items_by_key[key] = item

        supplier_id = None
        if data.get("supplier"):
            supplier_key = _norm(data["supplier"])
            supplier = (
                suppliers.get(supplier_key)
                or db.execute(
                    select(Supplier).where(
                        Supplier.organization_id == ctx.organization_id,
                        func.lower(Supplier.name) == supplier_key,
                    )
                )
                .scalars()
                .first()
            )
            if supplier is None:
                supplier = Supplier(organization_id=ctx.organization_id, name=data["supplier"])
                db.add(supplier)
                db.flush()
                created_suppliers += 1
            suppliers[supplier_key] = supplier
            supplier_id = supplier.id

        _new_observation(
            db,
            ctx,
            item,
            schemas.ObservationIn(
                price=Decimal(data["price"]),
                currency=data["currency"],
                unit=data["unit"],
                supplier_id=supplier_id,
                source_reference=data.get("source_reference")
                or f"Impor {job.filename} baris {row['row']}",
                source_url=data.get("source_url"),
                observed_at=date.fromisoformat(data["observed_at"]),
                valid_from=date.fromisoformat(data["valid_from"])
                if data.get("valid_from")
                else None,
                valid_until=date.fromisoformat(data["valid_until"])
                if data.get("valid_until")
                else None,
                location=data.get("location"),
                notes=data.get("notes"),
            ),
            source_type=ObservationSource.IMPORT,
            import_job_id=job.id,
        )
        created_prices += 1

    job.status = ImportStatus.COMMITTED
    job.committed_at = datetime.now(UTC)
    job.committed_by_id = ctx.user_id
    job.result = {
        "items_created": created_items,
        "prices_created": created_prices,
        "suppliers_created": created_suppliers,
    }
    # Rows may have been re-flagged during commit; the JSON column needs an explicit reassign.
    job.rows = [dict(r) for r in job.rows]
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="price_import.commit",
        entity_type="import_job",
        entity_id=job.id,
        summary=f"{job.filename}: {created_prices} harga, {created_items} item baru",
        changes={k: {"from": None, "to": v} for k, v in job.result.items()},
        ip_address=ctx.ip_address,
    )
    db.commit()
    return job


def discard(db: Session, ctx: RequestContext, job_id: uuid.UUID) -> ImportJob:
    job = get_job(db, ctx, job_id, lock=True)
    if job.status is ImportStatus.COMMITTED:
        raise ConflictError("Impor yang sudah disimpan tidak dapat dibatalkan.")
    job.status = ImportStatus.DISCARDED
    db.commit()
    return job


def to_out(job: ImportJob) -> schemas.ImportJobOut:
    return schemas.ImportJobOut(
        id=job.id,
        status=job.status,
        filename=job.filename,
        row_count=job.row_count,
        valid_count=sum(1 for r in job.rows if r["valid"]),
        error_count=sum(1 for r in job.rows if not r["valid"]),
        warnings=job.warnings or [],
        rows=[
            schemas.ImportRowOut(
                row=r["row"],
                valid=r["valid"],
                errors=r["errors"],
                data=r["data"],
                action=r.get("action"),
            )
            for r in job.rows
        ],
        result=job.result,
        created_at=job.created_at,
        committed_at=job.committed_at,
    )
