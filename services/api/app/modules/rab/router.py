from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import BusinessValidationError, ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import UserBrief
from app.modules.rab import schemas, service
from app.modules.rab.lifecycle import RabAction, allowed_actions
from app.modules.rab.models import OPEN_STATUSES, RabDocument, RabItem, RabStatus, RabVersion

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}

router = APIRouter(prefix="/rab", tags=["rab"], responses=ERRORS)
project_router = APIRouter(prefix="/projects/{project_id}/rab", tags=["rab"], responses=ERRORS)
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"], responses=ERRORS)


# --------------------------------------------------------------------------- mapping


def _project_ref(rab: RabDocument) -> schemas.ProjectRef:
    return schemas.ProjectRef.model_validate(rab.project)


def _rab_out(rab: RabDocument) -> schemas.RabOut:
    return schemas.RabOut(
        id=rab.id,
        number=rab.number,
        title=rab.title,
        project=_project_ref(rab),
        versions=[schemas.VersionSummary.model_validate(v) for v in rab.versions],
        created_at=rab.created_at,
        updated_at=rab.updated_at,
    )


def _list_item(rab: RabDocument, version: RabVersion) -> schemas.RabListItem:
    return schemas.RabListItem(
        id=rab.id,
        number=rab.number,
        title=rab.title,
        project=_project_ref(rab),
        latest_version_no=version.version_no,
        latest_status=version.status,
        currency=version.currency,
        grand_total=version.grand_total,
        updated_at=max(rab.updated_at, version.updated_at),
    )


def _item_out(item: RabItem) -> schemas.ItemOut:
    observation = item.price_observation
    return schemas.ItemOut.model_validate(
        {
            **{
                field: getattr(item, field)
                for field in schemas.ItemOut.model_fields
                if field != "price_verification_status"
            },
            "price_verification_status": observation.verification_status.value
            if observation
            else None,
        }
    )


def _version_out(db: Session, ctx: RequestContext, version: RabVersion) -> schemas.VersionOut:
    rab = service.get_rab(db, ctx, version.rab_id)
    has_open = any(v.status in OPEN_STATUSES for v in rab.versions)
    return schemas.VersionOut(
        id=version.id,
        version_no=version.version_no,
        status=version.status,
        grand_total=version.grand_total,
        currency=version.currency,
        created_at=version.created_at,
        decided_at=version.decided_at,
        based_on_version_id=version.based_on_version_id,
        tax_label=version.tax_label,
        tax_rate_percent=version.tax_rate_percent,
        discount_type=version.discount_type,
        discount_value=version.discount_value,
        notes=version.notes,
        assumptions=version.assumptions,
        totals=schemas.Totals.model_validate(version),
        items=[_item_out(i) for i in version.items],
        issues=[
            schemas.IssueOut(severity=i.severity, code=i.code, message=i.message, item_id=i.item_id)
            for i in service.issues_of(version)
        ],
        approvals=[
            schemas.ApprovalOut.model_validate(a) for a in service.approvals_of(db, ctx, version)
        ],
        submitted_by=UserBrief.model_validate(version.submitted_by)
        if version.submitted_by
        else None,
        submitted_at=version.submitted_at,
        decided_by=UserBrief.model_validate(version.decided_by) if version.decided_by else None,
        lock_version=version.lock_version,
        editable=version.status is RabStatus.DRAFT and ctx.can(Permission.RAB_WRITE),
        allowed_actions=allowed_actions(version.status, ctx.permissions),
        can_create_version=ctx.can(Permission.RAB_WRITE) and not has_open,
    )


# --------------------------------------------------------------------------- per project


@project_router.get("", response_model=Page[schemas.RabListItem], summary="RAB milik proyek")
def list_project_rabs(
    project_id: uuid.UUID,
    params: PageParams = Depends(page_params),
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.RabListItem]:
    rows, total = service.list_rabs(
        db, ctx, params, q=None, status=None, project_id=project_id, sort=None
    )
    return Page[schemas.RabListItem](
        items=[_list_item(r, v) for r, v in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@project_router.post(
    "",
    response_model=schemas.RabOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat RAB (versi 1, draft) untuk proyek",
)
def create_rab(
    project_id: uuid.UUID,
    payload: schemas.RabCreate,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.RabOut:
    return _rab_out(service.create_rab(db, ctx, project_id, payload))


# --------------------------------------------------------------------------- RAB documents


@router.get("", response_model=Page[schemas.RabListItem], summary="Daftar RAB")
def list_rabs(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100, description="Cari nomor, judul, proyek"),
    status_filter: RabStatus | None = Query(
        None, alias="status", description="Status versi terbaru"
    ),
    project_id: uuid.UUID | None = Query(None),
    sort: str | None = Query(None, description="number, title, updated_at, grand_total; awali '-'"),
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.RabListItem]:
    rows, total = service.list_rabs(
        db, ctx, params, q=q, status=status_filter, project_id=project_id, sort=sort
    )
    return Page[schemas.RabListItem](
        items=[_list_item(r, v) for r, v in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{rab_id}", response_model=schemas.RabOut, summary="Detail RAB dan daftar versinya")
def get_rab(
    rab_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> schemas.RabOut:
    return _rab_out(service.get_rab(db, ctx, rab_id))


@router.patch("/{rab_id}", response_model=schemas.RabOut, summary="Ubah judul RAB")
def update_rab(
    rab_id: uuid.UUID,
    payload: schemas.RabUpdate,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.RabOut:
    return _rab_out(service.update_rab(db, ctx, rab_id, payload))


@router.delete(
    "/{rab_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus RAB yang belum pernah disetujui",
)
def delete_rab(
    rab_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> Response:
    service.delete_rab(db, ctx, rab_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{rab_id}/duplicate",
    response_model=schemas.RabOut,
    status_code=status.HTTP_201_CREATED,
    summary="Gandakan RAB (versi terpilih) menjadi RAB baru",
)
def duplicate_rab(
    rab_id: uuid.UUID,
    payload: schemas.DuplicateRequest,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.RabOut:
    return _rab_out(service.duplicate_rab(db, ctx, rab_id, payload))


@router.get("/{rab_id}/compare", response_model=schemas.CompareOut, summary="Bandingkan dua versi")
def compare(
    rab_id: uuid.UUID,
    from_version: int = Query(..., ge=1, alias="from"),
    to_version: int = Query(..., ge=1, alias="to"),
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> schemas.CompareOut:
    if from_version == to_version:
        raise BusinessValidationError("Pilih dua versi yang berbeda.")
    return service.compare_versions(db, ctx, rab_id, from_version, to_version)


# --------------------------------------------------------------------------- versions


@router.post(
    "/{rab_id}/versions",
    response_model=schemas.VersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat versi baru (draft) dari versi tertentu",
)
def create_version(
    rab_id: uuid.UUID,
    payload: schemas.NewVersionRequest,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.VersionOut:
    return _version_out(db, ctx, service.create_version(db, ctx, rab_id, payload.from_version_no))


@router.get(
    "/{rab_id}/versions/{version_no}", response_model=schemas.VersionOut, summary="Isi versi RAB"
)
def get_version(
    rab_id: uuid.UUID,
    version_no: int,
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> schemas.VersionOut:
    return _version_out(db, ctx, service.get_version(db, ctx, rab_id, version_no))


@router.patch(
    "/{rab_id}/versions/{version_no}",
    response_model=schemas.VersionOut,
    summary="Ubah pajak, diskon, catatan, asumsi (draft)",
)
def update_version(
    rab_id: uuid.UUID,
    version_no: int,
    payload: schemas.VersionUpdate,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.VersionOut:
    return _version_out(db, ctx, service.update_header(db, ctx, rab_id, version_no, payload))


@router.post(
    "/{rab_id}/versions/{version_no}/items",
    response_model=schemas.VersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tambah item",
)
def add_item(
    rab_id: uuid.UUID,
    version_no: int,
    payload: schemas.ItemCreate,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.VersionOut:
    return _version_out(db, ctx, service.add_item(db, ctx, rab_id, version_no, payload))


@router.put(
    "/{rab_id}/versions/{version_no}/items/{item_id}",
    response_model=schemas.VersionOut,
    summary="Ubah item (row_version wajib)",
)
def update_item(
    rab_id: uuid.UUID,
    version_no: int,
    item_id: uuid.UUID,
    payload: schemas.ItemUpdate,
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.VersionOut:
    return _version_out(db, ctx, service.update_item(db, ctx, rab_id, version_no, item_id, payload))


@router.delete(
    "/{rab_id}/versions/{version_no}/items/{item_id}",
    response_model=schemas.VersionOut,
    summary="Hapus item (row_version wajib)",
)
def delete_item(
    rab_id: uuid.UUID,
    version_no: int,
    item_id: uuid.UUID,
    row_version: int = Query(..., ge=1),
    ctx: RequestContext = Depends(require(Permission.RAB_WRITE)),
    db: Session = Depends(get_db),
) -> schemas.VersionOut:
    return _version_out(
        db, ctx, service.delete_item(db, ctx, rab_id, version_no, item_id, row_version)
    )


@router.post(
    "/{rab_id}/versions/{version_no}/transitions/{action}",
    response_model=schemas.VersionOut,
    summary="Ubah status versi: submit, withdraw, approve, reject, reopen, archive",
)
def transition(
    rab_id: uuid.UUID,
    version_no: int,
    action: RabAction,
    payload: schemas.TransitionRequest,
    ctx: RequestContext = Depends(require(Permission.RAB_READ)),
    db: Session = Depends(get_db),
) -> schemas.VersionOut:
    # The action's own permission (rab.write or rab.approve) is checked by the service.
    return _version_out(
        db, ctx, service.transition(db, ctx, rab_id, version_no, action, payload.note)
    )


# --------------------------------------------------------------------------- approvals


@approvals_router.get(
    "/pending", response_model=list[schemas.PendingApproval], summary="Antrian approval RAB"
)
def pending(
    ctx: RequestContext = Depends(require(Permission.RAB_APPROVE)),
    db: Session = Depends(get_db),
) -> list[schemas.PendingApproval]:
    return [
        schemas.PendingApproval(
            rab_id=rab.id,
            number=rab.number,
            title=rab.title,
            project=_project_ref(rab),
            version_no=version.version_no,
            currency=version.currency,
            grand_total=version.grand_total,
            submitted_by=UserBrief.model_validate(version.submitted_by)
            if version.submitted_by
            else None,
            submitted_at=version.submitted_at,
        )
        for rab, version in service.pending_approvals(db, ctx)
    ]
