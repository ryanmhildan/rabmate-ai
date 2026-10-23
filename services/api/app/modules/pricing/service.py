"""Price catalog business logic. Every query is scoped to ctx.organization_id."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import (
    BusinessValidationError,
    ConflictError,
    NotFoundError,
)
from app.core.pagination import PageParams, apply_sort, escape_like, paginate
from app.modules.audit import service as audit
from app.modules.pricing import schemas
from app.modules.pricing.matching import Candidate, Query, score
from app.modules.pricing.models import (
    ObservationSource,
    PriceCatalogItem,
    PriceObservation,
    Supplier,
    VerificationStatus,
)
from app.modules.pricing.units import same_unit
from app.modules.rab.models import RabDocument, RabItem, RabItemType, RabStatus, RabVersion
from app.shared.concurrency import check_version

SUPPLIER_FIELDS = (
    "name",
    "contact_person",
    "phone",
    "email",
    "city",
    "address",
    "notes",
    "is_active",
)
ITEM_FIELDS = (
    "code",
    "name",
    "category",
    "brand",
    "specification",
    "unit",
    "item_type",
    "notes",
    "is_active",
)
ITEM_SORT = {
    "name": PriceCatalogItem.name,
    "code": PriceCatalogItem.code,
    "category": PriceCatalogItem.category,
    "updated_at": PriceCatalogItem.updated_at,
}
SUPPLIER_SORT = {"name": Supplier.name, "updated_at": Supplier.updated_at}

# Search tuning: pg_trgm similarity floor and how many rows are scored in Python.
SIMILARITY_FLOOR = 0.2
CANDIDATE_POOL = 50


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


# --------------------------------------------------------------------------- suppliers


def get_supplier(db: Session, ctx: RequestContext, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.execute(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.organization_id == ctx.organization_id
        )
    ).scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier tidak ditemukan.")
    return supplier


def list_suppliers(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    is_active: bool | None,
    sort: str | None,
) -> tuple[list[Supplier], int]:
    stmt = select(Supplier).where(Supplier.organization_id == ctx.organization_id)
    if q:
        term = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(Supplier.name.ilike(term, escape="\\"), Supplier.city.ilike(term, escape="\\"))
        )
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active.is_(is_active))
    return paginate(db, apply_sort(stmt, sort, SUPPLIER_SORT, default="name"), params)


def create_supplier(db: Session, ctx: RequestContext, payload: schemas.SupplierIn) -> Supplier:
    supplier = Supplier(organization_id=ctx.organization_id, **payload.model_dump())
    db.add(supplier)
    db.flush()
    _audit(db, ctx, "supplier.create", "supplier", supplier.id, supplier.name)
    db.commit()
    return supplier


def update_supplier(
    db: Session, ctx: RequestContext, supplier_id: uuid.UUID, payload: schemas.SupplierUpdate
) -> Supplier:
    supplier = get_supplier(db, ctx, supplier_id)
    check_version(supplier.version, payload.version)
    before = audit.snapshot(supplier, SUPPLIER_FIELDS)
    for field, value in payload.model_dump(exclude={"version"}).items():
        setattr(supplier, field, value)
    changes = audit.diff(before, audit.snapshot(supplier, SUPPLIER_FIELDS))
    if changes:
        db.flush()
        _audit(db, ctx, "supplier.update", "supplier", supplier.id, supplier.name, changes)
    db.commit()
    db.refresh(supplier)
    return supplier


# --------------------------------------------------------------------------- catalog items


def get_item(db: Session, ctx: RequestContext, item_id: uuid.UUID) -> PriceCatalogItem:
    item = db.execute(
        select(PriceCatalogItem).where(
            PriceCatalogItem.id == item_id,
            PriceCatalogItem.organization_id == ctx.organization_id,
        )
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item katalog tidak ditemukan.")
    return item


def list_items(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    category: str | None,
    item_type: RabItemType | None,
    is_active: bool | None,
    sort: str | None,
) -> tuple[list[PriceCatalogItem], int]:
    stmt = select(PriceCatalogItem).where(PriceCatalogItem.organization_id == ctx.organization_id)
    if q:
        term = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(
                PriceCatalogItem.name.ilike(term, escape="\\"),
                PriceCatalogItem.code.ilike(term, escape="\\"),
                PriceCatalogItem.brand.ilike(term, escape="\\"),
                PriceCatalogItem.specification.ilike(term, escape="\\"),
            )
        )
    if category:
        stmt = stmt.where(PriceCatalogItem.category == category)
    if item_type is not None:
        stmt = stmt.where(PriceCatalogItem.item_type == item_type)
    if is_active is not None:
        stmt = stmt.where(PriceCatalogItem.is_active.is_(is_active))
    return paginate(db, apply_sort(stmt, sort, ITEM_SORT, default="name"), params)


def categories(db: Session, ctx: RequestContext) -> list[str]:
    rows = db.execute(
        select(PriceCatalogItem.category)
        .where(
            PriceCatalogItem.organization_id == ctx.organization_id,
            PriceCatalogItem.category.is_not(None),
        )
        .distinct()
        .order_by(PriceCatalogItem.category)
    ).scalars()
    return [category for category in rows if category is not None]


@dataclass(frozen=True)
class Summary:
    latest_verified: PriceObservation | None
    latest_any: PriceObservation | None
    count: int


def _latest(
    db: Session, ctx: RequestContext, item_ids: Sequence[uuid.UUID], *, verified_only: bool
) -> dict[uuid.UUID, PriceObservation]:
    if not item_ids:
        return {}
    stmt = (
        select(PriceObservation)
        .where(
            PriceObservation.organization_id == ctx.organization_id,
            PriceObservation.catalog_item_id.in_(item_ids),
        )
        .order_by(
            PriceObservation.catalog_item_id,
            PriceObservation.observed_at.desc(),
            PriceObservation.created_at.desc(),
        )
        .ext(distinct_on(PriceObservation.catalog_item_id))
    )
    if verified_only:
        stmt = stmt.where(PriceObservation.verification_status == VerificationStatus.VERIFIED)
    else:
        stmt = stmt.where(PriceObservation.verification_status != VerificationStatus.REJECTED)
    return {o.catalog_item_id: o for o in db.execute(stmt).unique().scalars()}


def summaries(
    db: Session, ctx: RequestContext, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Summary]:
    verified = _latest(db, ctx, item_ids, verified_only=True)
    latest = _latest(db, ctx, item_ids, verified_only=False)
    counts = (
        dict(
            db.execute(
                select(PriceObservation.catalog_item_id, func.count())
                .where(
                    PriceObservation.organization_id == ctx.organization_id,
                    PriceObservation.catalog_item_id.in_(item_ids),
                )
                .group_by(PriceObservation.catalog_item_id)
            ).all()
        )
        if item_ids
        else {}
    )
    return {
        item_id: Summary(verified.get(item_id), latest.get(item_id), counts.get(item_id, 0))
        for item_id in item_ids
    }


def observations_of(db: Session, ctx: RequestContext, item_id: uuid.UUID) -> list[PriceObservation]:
    return list(
        db.execute(
            select(PriceObservation)
            .where(
                PriceObservation.organization_id == ctx.organization_id,
                PriceObservation.catalog_item_id == item_id,
            )
            .order_by(PriceObservation.observed_at.desc(), PriceObservation.created_at.desc())
        )
        .unique()
        .scalars()
    )


def _duplicate_code(exc: IntegrityError) -> bool:
    return "uq_price_catalog_items_organization_id_code" in str(exc.orig)


def create_item(
    db: Session, ctx: RequestContext, payload: schemas.CatalogItemCreate
) -> PriceCatalogItem:
    data = payload.model_dump(exclude={"initial_price"})
    item = PriceCatalogItem(organization_id=ctx.organization_id, created_by_id=ctx.user_id, **data)
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _duplicate_code(exc):
            raise ConflictError("Kode item katalog sudah dipakai.") from None
        raise
    _audit(db, ctx, "catalog_item.create", "catalog_item", item.id, item.name)
    if payload.initial_price is not None:
        _new_observation(db, ctx, item, payload.initial_price)
    db.commit()
    return item


def update_item(
    db: Session, ctx: RequestContext, item_id: uuid.UUID, payload: schemas.CatalogItemUpdate
) -> PriceCatalogItem:
    item = get_item(db, ctx, item_id)
    check_version(item.version, payload.version)
    if not same_unit(item.unit, payload.unit) and _has_observations(db, ctx, item.id):
        # Existing prices were quoted per the old unit; changing it would silently relabel them.
        raise ConflictError(
            "Satuan tidak dapat diubah karena item sudah memiliki riwayat harga. "
            "Buat item katalog baru untuk satuan lain."
        )
    before = audit.snapshot(item, ITEM_FIELDS)
    for field, value in payload.model_dump(exclude={"version"}).items():
        setattr(item, field, value)
    changes = audit.diff(before, audit.snapshot(item, ITEM_FIELDS))
    if changes:
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            if _duplicate_code(exc):
                raise ConflictError("Kode item katalog sudah dipakai.") from None
            raise
        _audit(db, ctx, "catalog_item.update", "catalog_item", item.id, item.name, changes)
    db.commit()
    db.refresh(item)
    return item


def _has_observations(db: Session, ctx: RequestContext, item_id: uuid.UUID) -> bool:
    return bool(
        db.execute(
            select(func.count())
            .select_from(PriceObservation)
            .where(
                PriceObservation.organization_id == ctx.organization_id,
                PriceObservation.catalog_item_id == item_id,
            )
        ).scalar_one()
    )


# --------------------------------------------------------------------------- observations


def get_observation(
    db: Session, ctx: RequestContext, observation_id: uuid.UUID, *, lock: bool = False
) -> PriceObservation:
    # populate_existing: relationships such as verified_by must reflect the stored row, not
    # what was loaded earlier in this session (verified_by was None before verification).
    stmt = (
        select(PriceObservation)
        .where(
            PriceObservation.id == observation_id,
            PriceObservation.organization_id == ctx.organization_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=PriceObservation)
    observation = db.execute(stmt).unique().scalar_one_or_none()
    if observation is None:
        raise NotFoundError("Data harga tidak ditemukan.")
    return observation


def _new_observation(
    db: Session,
    ctx: RequestContext,
    item: PriceCatalogItem,
    payload: schemas.ObservationIn,
    *,
    source_type: ObservationSource | None = None,
    import_job_id: uuid.UUID | None = None,
) -> PriceObservation:
    if payload.unit is not None and not same_unit(payload.unit, item.unit):
        raise BusinessValidationError(
            f"Satuan harga ({payload.unit}) berbeda dengan satuan item ({item.unit}). "
            "Buat item katalog terpisah untuk satuan lain.",
            details=[{"loc": ["body", "unit"], "msg": "Satuan berbeda."}],
        )
    if payload.supplier_id is not None:
        get_supplier(db, ctx, payload.supplier_id)
    data = payload.model_dump(exclude={"unit"})
    if source_type is not None:
        data["source_type"] = source_type
    observation = PriceObservation(
        organization_id=ctx.organization_id,
        catalog_item_id=item.id,
        unit=item.unit,
        verification_status=VerificationStatus.UNVERIFIED,
        import_job_id=import_job_id,
        created_by_id=ctx.user_id,
        **data,
    )
    db.add(observation)
    db.flush()
    _audit(
        db,
        ctx,
        "price_observation.create",
        "catalog_item",
        item.id,
        f"{item.name}: {observation.currency} {observation.price}",
        {"price": {"from": None, "to": observation.price}},
    )
    return observation


def add_observation(
    db: Session, ctx: RequestContext, item_id: uuid.UUID, payload: schemas.ObservationIn
) -> PriceObservation:
    item = get_item(db, ctx, item_id)
    observation = _new_observation(db, ctx, item, payload)
    db.commit()
    return get_observation(db, ctx, observation.id)


_VERIFY_FROM: dict[VerificationStatus, frozenset[VerificationStatus]] = {
    VerificationStatus.VERIFIED: frozenset({VerificationStatus.UNVERIFIED}),
    # A verified price found to be wrong later can still be rejected.
    VerificationStatus.REJECTED: frozenset(
        {VerificationStatus.UNVERIFIED, VerificationStatus.VERIFIED}
    ),
}


def has_source(observation: PriceObservation) -> bool:
    return bool(observation.source_reference or observation.source_url or observation.supplier_id)


def verify_observation(
    db: Session, ctx: RequestContext, observation_id: uuid.UUID, payload: schemas.VerificationIn
) -> PriceObservation:
    observation = get_observation(db, ctx, observation_id, lock=True)
    target = VerificationStatus(payload.status)
    if observation.verification_status not in _VERIFY_FROM[target]:
        raise ConflictError(
            f"Harga berstatus '{observation.verification_status.value}' tidak dapat diubah "
            f"menjadi '{target.value}'."
        )
    if target is VerificationStatus.VERIFIED and not has_source(observation):
        raise BusinessValidationError(
            "Harga tanpa sumber (supplier, referensi, atau URL) tidak dapat diverifikasi."
        )
    if target is VerificationStatus.REJECTED and not payload.note:
        raise BusinessValidationError(
            "Alasan penolakan wajib diisi.",
            details=[{"loc": ["body", "note"], "msg": "Wajib diisi."}],
        )
    before = observation.verification_status
    observation.verification_status = target
    observation.verified_by_id = ctx.user_id
    observation.verified_at = datetime.now(UTC)
    observation.verification_note = payload.note
    db.flush()
    _audit(
        db,
        ctx,
        f"price_observation.{'verify' if target is VerificationStatus.VERIFIED else 'reject'}",
        "catalog_item",
        observation.catalog_item_id,
        f"{observation.item.name}: {observation.currency} {observation.price}",
        {"verification_status": {"from": before.value, "to": target.value}}
        | ({"note": {"from": None, "to": payload.note}} if payload.note else {}),
    )
    db.commit()
    return get_observation(db, ctx, observation_id)


# --------------------------------------------------------------------------- candidates


def _search_terms(name: str) -> list[str]:
    return [t for t in name.lower().split() if len(t) >= 3][:6]


def find_candidates(
    db: Session,
    ctx: RequestContext,
    query: Query,
    *,
    currency: str = "IDR",
    limit: int = 10,
) -> list[schemas.CandidateOut]:
    today = _today()
    needle = query.name.strip().lower()
    terms = _search_terms(needle)
    results: list[schemas.CandidateOut] = []

    # 1) Catalog: trigram similarity on the name, plus plain substring matches on its words.
    similarity = func.similarity(func.lower(PriceCatalogItem.name), needle)
    name_filters = [similarity >= SIMILARITY_FLOOR] + [
        PriceCatalogItem.name.ilike(f"%{escape_like(t)}%", escape="\\") for t in terms
    ]
    items = list(
        db.execute(
            select(PriceCatalogItem)
            .where(
                PriceCatalogItem.organization_id == ctx.organization_id,
                PriceCatalogItem.is_active.is_(True),
                or_(*name_filters),
            )
            .order_by(similarity.desc())
            .limit(CANDIDATE_POOL)
        ).scalars()
    )
    if items:
        ids = [i.id for i in items]
        verified = _latest(db, ctx, ids, verified_only=True)
        latest = _latest(db, ctx, ids, verified_only=False)
        for item in items:
            observation = verified.get(item.id) or latest.get(item.id)
            if observation is None or observation.currency != currency:
                continue
            result = score(
                query,
                Candidate(
                    name=item.name,
                    unit=item.unit,
                    specification=item.specification,
                    brand=item.brand,
                    location=observation.location,
                    observed_at=observation.observed_at,
                    verified=observation.verification_status is VerificationStatus.VERIFIED,
                ),
                today=today,
            )
            results.append(
                schemas.CandidateOut(
                    kind="catalog",
                    score=result.score,
                    level=result.level,
                    unit_compatible=result.unit_compatible,
                    reasons=result.reasons,
                    warnings=result.warnings,
                    name=item.name,
                    unit=item.unit,
                    brand=item.brand,
                    specification=item.specification,
                    price=observation.price,
                    currency=observation.currency,
                    observed_at=observation.observed_at,
                    verified=observation.verification_status is VerificationStatus.VERIFIED,
                    catalog_item_id=item.id,
                    observation_id=observation.id,
                    supplier=observation.supplier.name if observation.supplier else None,
                    source_reference=observation.source_reference,
                )
            )

    # 2) Project history: priced items of currently approved RAB versions.
    rab_similarity = func.similarity(func.lower(RabItem.name), needle)
    history = (
        db.execute(
            select(RabItem, RabVersion, RabDocument)
            .join(RabVersion, RabVersion.id == RabItem.version_id)
            .join(RabDocument, RabDocument.id == RabVersion.rab_id)
            .where(
                RabItem.organization_id == ctx.organization_id,
                RabVersion.status == RabStatus.APPROVED,
                RabVersion.currency == currency,
                RabItem.unit_price.is_not(None),
                or_(
                    rab_similarity >= SIMILARITY_FLOOR,
                    *[RabItem.name.ilike(f"%{escape_like(t)}%", escape="\\") for t in terms],
                ),
            )
            .order_by(rab_similarity.desc())
            .limit(CANDIDATE_POOL)
        )
        .unique()
        .all()
    )
    for rab_item, version, rab in history:
        decided = version.decided_at.date() if version.decided_at else None
        result = score(
            query,
            Candidate(
                name=rab_item.name,
                unit=rab_item.unit,
                specification=rab_item.specification,
                observed_at=decided,
                verified=False,
            ),
            today=today,
        )
        reasons = [
            *result.reasons,
            "Harga dari RAB yang disetujui, bukan harga pasar terverifikasi.",
        ]
        results.append(
            schemas.CandidateOut(
                kind="history",
                score=result.score,
                level=result.level,
                unit_compatible=result.unit_compatible,
                reasons=reasons,
                warnings=[w for w in result.warnings if "terverifikasi" not in w],
                name=rab_item.name,
                unit=rab_item.unit,
                brand=None,
                specification=rab_item.specification,
                price=rab_item.unit_price or Decimal("0"),
                currency=version.currency,
                observed_at=decided,
                verified=False,
                reference=f"{rab.number} v{version.version_no} (disetujui)",
            )
        )

    results.sort(key=lambda c: (c.unit_compatible, c.score, c.verified), reverse=True)
    return results[:limit]


@dataclass(frozen=True)
class ResolvedPrice:
    observation: PriceObservation
    source_text: str


def resolve_for_rab(
    db: Session, ctx: RequestContext, observation_id: uuid.UUID, *, unit: str, currency: str
) -> ResolvedPrice:
    """Server-side lookup when a RAB item takes its price from the catalog (no client trust)."""
    observation = get_observation(db, ctx, observation_id)
    if observation.verification_status is VerificationStatus.REJECTED:
        raise BusinessValidationError("Harga katalog ini sudah ditolak dan tidak dapat dipakai.")
    if not same_unit(observation.unit, unit):
        raise BusinessValidationError(
            f"Satuan harga katalog ({observation.unit}) berbeda dengan satuan item ({unit})."
        )
    if observation.currency != currency:
        raise BusinessValidationError(
            f"Mata uang harga katalog ({observation.currency}) berbeda dengan RAB ({currency})."
        )
    item = observation.item
    status = (
        "terverifikasi"
        if observation.verification_status is VerificationStatus.VERIFIED
        else "belum terverifikasi"
    )
    parts = [
        f"Katalog: {item.code + ' ' if item.code else ''}{item.name}",
        observation.supplier.name if observation.supplier else None,
        observation.source_reference,
        observation.observed_at.isoformat(),
        status,
    ]
    return ResolvedPrice(observation, " · ".join(p for p in parts if p)[:500])


# --------------------------------------------------------------------------- audit


def _audit(
    db: Session,
    ctx: RequestContext,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    summary: str,
    changes: dict[str, object] | None = None,
) -> None:
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        changes=changes,
        ip_address=ctx.ip_address,
    )
