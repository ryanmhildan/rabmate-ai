from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.core.ratelimit import EXPENSIVE
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import UserBrief
from app.modules.pricing import external, imports, schemas, service
from app.modules.pricing.importer import MAX_BYTES, template_csv, template_xlsx
from app.modules.pricing.matching import Query as MatchQuery
from app.modules.pricing.models import PriceCatalogItem, PriceObservation
from app.modules.rab.models import RabItemType

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422)
}

suppliers_router = APIRouter(prefix="/suppliers", tags=["pricing"], responses=ERRORS)
catalog_router = APIRouter(prefix="/price-catalog", tags=["pricing"], responses=ERRORS)
observations_router = APIRouter(prefix="/price-observations", tags=["pricing"], responses=ERRORS)
sources_router = APIRouter(prefix="/price-sources", tags=["pricing"], responses=ERRORS)


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    message = f"Ukuran file melebihi {MAX_BYTES // (1024 * 1024)} MB."


# --------------------------------------------------------------------------- mapping


def observation_out(observation: PriceObservation) -> schemas.ObservationOut:
    return schemas.ObservationOut(
        id=observation.id,
        catalog_item_id=observation.catalog_item_id,
        price=observation.price,
        currency=observation.currency,
        unit=observation.unit,
        supplier=schemas.SupplierBrief.model_validate(observation.supplier)
        if observation.supplier
        else None,
        source_type=observation.source_type,
        source_reference=observation.source_reference,
        source_url=observation.source_url,
        observed_specification=observation.observed_specification,
        match_level=observation.match_level,
        observed_at=observation.observed_at,
        valid_from=observation.valid_from,
        valid_until=observation.valid_until,
        location=observation.location,
        verification_status=observation.verification_status,
        verified_by=UserBrief.model_validate(observation.verified_by)
        if observation.verified_by
        else None,
        verified_at=observation.verified_at,
        verification_note=observation.verification_note,
        notes=observation.notes,
        import_job_id=observation.import_job_id,
        created_at=observation.created_at,
    )


def _summary(summary: service.Summary) -> schemas.PriceSummary:
    return schemas.PriceSummary(
        latest_verified=observation_out(summary.latest_verified)
        if summary.latest_verified
        else None,
        latest_any=observation_out(summary.latest_any) if summary.latest_any else None,
        observation_count=summary.count,
    )


def _detail(db: Session, ctx: RequestContext, item: PriceCatalogItem) -> schemas.CatalogItemDetail:
    summary = service.summaries(db, ctx, [item.id])[item.id]
    return schemas.CatalogItemDetail(
        **schemas.CatalogItemOut.model_validate(item).model_dump(),
        observations=[observation_out(o) for o in service.observations_of(db, ctx, item.id)],
        prices=_summary(summary),
    )


# --------------------------------------------------------------------------- suppliers


@suppliers_router.get("", response_model=Page[schemas.SupplierOut], summary="Daftar supplier")
def list_suppliers(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100),
    is_active: bool | None = Query(None),
    sort: str | None = Query(None),
    ctx: RequestContext = Depends(require(Permission.PRICING_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.SupplierOut]:
    items, total = service.list_suppliers(db, ctx, params, q=q, is_active=is_active, sort=sort)
    return Page[schemas.SupplierOut](
        items=[schemas.SupplierOut.model_validate(s) for s in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@suppliers_router.post(
    "",
    response_model=schemas.SupplierOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tambah supplier",
)
def create_supplier(
    payload: schemas.SupplierIn,
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.SupplierOut:
    return schemas.SupplierOut.model_validate(service.create_supplier(db, ctx, payload))


@suppliers_router.patch(
    "/{supplier_id}", response_model=schemas.SupplierOut, summary="Ubah supplier"
)
def update_supplier(
    supplier_id: uuid.UUID,
    payload: schemas.SupplierUpdate,
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.SupplierOut:
    return schemas.SupplierOut.model_validate(
        service.update_supplier(db, ctx, supplier_id, payload)
    )


# ------------------------------------------------- catalog (static paths before /{item_id})


@catalog_router.get("/categories", response_model=list[str], summary="Kategori yang dipakai")
def list_categories(
    ctx: RequestContext = Depends(require(Permission.PRICING_READ)),
    db: Session = Depends(get_db),
) -> list[str]:
    return service.categories(db, ctx)


@catalog_router.get(
    "/candidates",
    response_model=list[schemas.CandidateOut],
    summary="Kandidat harga untuk sebuah item (katalog + riwayat RAB disetujui)",
)
def candidates(
    name: str = Query(..., min_length=2, max_length=300),
    unit: str | None = Query(None, max_length=32),
    specification: str | None = Query(None, max_length=2000),
    brand: str | None = Query(None, max_length=100),
    location: str | None = Query(None, max_length=100),
    currency: str = Query("IDR", pattern=r"^[A-Z]{3}$"),
    limit: int = Query(10, ge=1, le=30),
    ctx: RequestContext = Depends(require(Permission.PRICING_READ)),
    db: Session = Depends(get_db),
) -> list[schemas.CandidateOut]:
    query = MatchQuery(
        name=name, unit=unit, specification=specification, brand=brand, location=location
    )
    return service.find_candidates(db, ctx, query, currency=currency, limit=limit)


@catalog_router.get("/imports/template", summary="Template impor (xlsx atau csv)")
def import_template(
    format: Literal["xlsx", "csv"] = Query("xlsx"),
    _: RequestContext = Depends(require(Permission.PRICING_READ)),
) -> Response:
    if format == "csv":
        return Response(
            template_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="template-katalog-harga.csv"'},
        )
    return Response(
        template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template-katalog-harga.xlsx"'},
    )


@catalog_router.post(
    "/imports",
    dependencies=EXPENSIVE,
    response_model=schemas.ImportJobOut,
    status_code=status.HTTP_201_CREATED,
    summary="Unggah CSV/XLSX → pratinjau (belum disimpan)",
)
def upload_import(
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.ImportJobOut:
    content = file.file.read(MAX_BYTES + 1)  # bounded read; never loads more than the limit
    if len(content) > MAX_BYTES:
        raise PayloadTooLargeError()
    job = imports.preview(db, ctx, imports.safe_filename(file.filename), content)
    return imports.to_out(job)


@catalog_router.get(
    "/imports/{job_id}", response_model=schemas.ImportJobOut, summary="Pratinjau impor"
)
def get_import(
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.PRICING_READ)),
    db: Session = Depends(get_db),
) -> schemas.ImportJobOut:
    return imports.to_out(imports.get_job(db, ctx, job_id))


@catalog_router.post(
    "/imports/{job_id}/commit",
    dependencies=EXPENSIVE,
    response_model=schemas.ImportJobOut,
    summary="Simpan baris valid (idempoten)",
)
def commit_import(
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.ImportJobOut:
    return imports.to_out(imports.commit(db, ctx, job_id))


@catalog_router.post(
    "/imports/{job_id}/discard", response_model=schemas.ImportJobOut, summary="Batalkan impor"
)
def discard_import(
    job_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.ImportJobOut:
    return imports.to_out(imports.discard(db, ctx, job_id))


@catalog_router.get("", response_model=Page[schemas.CatalogListItem], summary="Daftar item katalog")
def list_items(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=100),
    item_type: RabItemType | None = Query(None),
    is_active: bool | None = Query(None),
    sort: str | None = Query(None, description="name, code, category, updated_at; awali '-'"),
    ctx: RequestContext = Depends(require(Permission.PRICING_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.CatalogListItem]:
    items, total = service.list_items(
        db, ctx, params, q=q, category=category, item_type=item_type, is_active=is_active, sort=sort
    )
    summaries = service.summaries(db, ctx, [i.id for i in items])
    return Page[schemas.CatalogListItem](
        items=[
            schemas.CatalogListItem(
                **schemas.CatalogItemOut.model_validate(i).model_dump(),
                prices=_summary(summaries[i.id]),
            )
            for i in items
        ],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@catalog_router.post(
    "",
    response_model=schemas.CatalogItemDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Tambah item katalog (opsional dengan harga awal)",
)
def create_item(
    payload: schemas.CatalogItemCreate,
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.CatalogItemDetail:
    return _detail(db, ctx, service.create_item(db, ctx, payload))


@catalog_router.get(
    "/{item_id}", response_model=schemas.CatalogItemDetail, summary="Item + riwayat harga"
)
def get_item(
    item_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.PRICING_READ)),
    db: Session = Depends(get_db),
) -> schemas.CatalogItemDetail:
    return _detail(db, ctx, service.get_item(db, ctx, item_id))


@catalog_router.patch(
    "/{item_id}", response_model=schemas.CatalogItemDetail, summary="Ubah item katalog"
)
def update_item(
    item_id: uuid.UUID,
    payload: schemas.CatalogItemUpdate,
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.CatalogItemDetail:
    return _detail(db, ctx, service.update_item(db, ctx, item_id, payload))


@catalog_router.post(
    "/{item_id}/observations",
    response_model=schemas.ObservationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Catat harga baru (riwayat; status awal belum terverifikasi)",
)
def add_observation(
    item_id: uuid.UUID,
    payload: schemas.ObservationIn,
    ctx: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.ObservationOut:
    return observation_out(service.add_observation(db, ctx, item_id, payload))


# --------------------------------------------------------------------------- observations


@observations_router.post(
    "/{observation_id}/verification",
    response_model=schemas.ObservationOut,
    summary="Verifikasi atau tolak harga",
)
def verify(
    observation_id: uuid.UUID,
    payload: schemas.VerificationIn,
    ctx: RequestContext = Depends(require(Permission.PRICING_VERIFY)),
    db: Session = Depends(get_db),
) -> schemas.ObservationOut:
    return observation_out(service.verify_observation(db, ctx, observation_id, payload))


# --------------------------------------------------------------------------- external


@sources_router.get(
    "/external", response_model=schemas.ExternalStatus, summary="Status pencarian eksternal"
)
def external_status(
    _: RequestContext = Depends(require(Permission.PRICING_READ)),
    settings: Settings = Depends(get_settings),
) -> schemas.ExternalStatus:
    return external.status(settings)


@sources_router.post(
    "/external/search",
    summary="Cari harga eksternal (503 bila belum dikonfigurasi)",
    responses={503: {"model": ErrorResponse}},
)
def external_search(
    name: str = Query(..., min_length=2, max_length=300),
    _: RequestContext = Depends(require(Permission.PRICING_WRITE)),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    return [vars(c) for c in external.search(settings, MatchQuery(name=name))]
