from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.core.ratelimit import EXPENSIVE
from app.db.session import get_db
from app.modules.billing import common
from app.modules.billing.models import DocStatus
from app.modules.billing.router import term_rows
from app.modules.billing.schemas import Brief, RefBrief, TransitionIn, VoidIn
from app.modules.billing.workflow import DELETABLE, Action, allowed_actions
from app.modules.documents.router import IdempotencyKey, file_response
from app.modules.documents.schemas import DocumentOut
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import UserBrief
from app.modules.rab.schemas import ApprovalOut
from app.modules.workorders import bast as bast_service
from app.modules.workorders import progress, schemas
from app.modules.workorders import spk as spk_service
from app.modules.workorders.models import Bast, BastKind, Spk

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}
P = Permission

spk_router = APIRouter(prefix="/spk", tags=["spk-bast"], responses=ERRORS)
bast_router = APIRouter(prefix="/bast", tags=["spk-bast"], responses=ERRORS)


def _user(user: Any) -> UserBrief | None:
    return UserBrief.model_validate(user) if user is not None else None


def _approvals(
    db: Session, ctx: RequestContext, entity: str, entity_id: uuid.UUID
) -> list[ApprovalOut]:
    return [ApprovalOut.model_validate(r) for r in common.approvals_of(db, ctx, entity, entity_id)]


def _project_brief(spk: Spk) -> Brief:
    return Brief(id=spk.project.id, number=spk.project.number, name=spk.project.name)


def _client_brief(spk: Spk) -> Brief:
    return Brief(id=spk.client.id, number=spk.client.code, name=spk.client.name)


# --------------------------------------------------------------------------- SPK mapping


def _spk_item(spk: Spk, bast_count: int) -> dict[str, Any]:
    return {
        "id": spk.id,
        "number": spk.number,
        "status": spk.status,
        "title": spk.title,
        "project": _project_brief(spk),
        "client": _client_brief(spk),
        "quotation": RefBrief(id=spk.quotation.id, number=spk.quotation.number),
        "currency": spk.currency,
        "contract_value": spk.contract_value,
        "issue_date": spk.issue_date,
        "start_date": spk.start_date,
        "end_date": spk.end_date,
        "bast_count": bast_count,
        "created_at": spk.created_at,
        "updated_at": spk.updated_at,
    }


def _spk_out(db: Session, ctx: RequestContext, spk: Spk) -> schemas.SpkOut:
    quotation = spk.quotation
    version = quotation.rab_version
    bast_count = spk_service.bast_counts(db, ctx, [spk.id]).get(spk.id, 0)
    issued = spk.status is DocStatus.ISSUED
    return schemas.SpkOut(
        **_spk_item(spk, bast_count),
        location=spk.location,
        scope=spk.scope,
        terms=spk.terms,
        notes=spk.notes,
        client_signatory_name=spk.client_signatory_name,
        client_signatory_title=spk.client_signatory_title,
        company_signatory_name=spk.company_signatory_name,
        company_signatory_title=spk.company_signatory_title,
        taxable_base=quotation.taxable_base,
        tax_label=quotation.tax_label,
        tax_rate_percent=quotation.tax_rate_percent,
        tax_amount=quotation.tax_amount,
        payment_terms=term_rows(db, quotation),
        rab=RefBrief(id=version.rab.id, number=version.rab.number),
        rab_version_no=version.version_no,
        submitted_by=_user(spk.submitted_by),
        submitted_at=spk.submitted_at,
        decided_by=_user(spk.decided_by),
        decided_at=spk.decided_at,
        voided_at=spk.voided_at,
        void_reason=spk.void_reason,
        version=spk.version,
        approvals=_approvals(db, ctx, spk_service.ENTITY, spk.id),
        allowed_actions=[
            a.value for a in allowed_actions(spk.status, ctx.permissions, write=spk_service.WRITE)
        ],
        editable=spk.status is DocStatus.DRAFT and ctx.can(spk_service.WRITE),
        can_issue=spk.status is DocStatus.APPROVED and ctx.can(P.DOCUMENTS_ISSUE),
        can_void=issued and bast_count == 0 and ctx.can(P.DOCUMENTS_ISSUE),
        can_delete=spk.status in DELETABLE and ctx.can(spk_service.WRITE),
        can_create_bast=issued and ctx.can(bast_service.WRITE),
    )


@spk_router.get("", response_model=Page[schemas.SpkListItem], summary="Daftar SPK")
def list_spk(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100),
    status_: DocStatus | None = Query(None, alias="status"),
    project_id: uuid.UUID | None = Query(None),
    quotation_id: uuid.UUID | None = Query(None),
    sort: str | None = Query(
        None, description="created_at, number, issue_date, contract_value; awali '-'"
    ),
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.SpkListItem]:
    items, total = spk_service.list_spk(
        db,
        ctx,
        params,
        q=q,
        status=status_,
        project_id=project_id,
        quotation_id=quotation_id,
        sort=sort,
    )
    counts = spk_service.bast_counts(db, ctx, [x.id for x in items])
    return Page(
        items=[schemas.SpkListItem(**_spk_item(x, counts.get(x.id, 0))) for x in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@spk_router.post(
    "",
    response_model=schemas.SpkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat SPK dari penawaran terbit yang diterima klien",
)
def create_spk(
    payload: schemas.SpkCreate,
    ctx: RequestContext = Depends(require(spk_service.WRITE)),
    db: Session = Depends(get_db),
) -> schemas.SpkOut:
    return _spk_out(db, ctx, spk_service.create(db, ctx, payload))


@spk_router.get("/{spk_id}", response_model=schemas.SpkOut, summary="Detail SPK")
def get_spk(
    spk_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> schemas.SpkOut:
    return _spk_out(db, ctx, spk_service.get(db, ctx, spk_id))


@spk_router.patch("/{spk_id}", response_model=schemas.SpkOut, summary="Ubah SPK (draft)")
def update_spk(
    spk_id: uuid.UUID,
    payload: schemas.SpkUpdate,
    ctx: RequestContext = Depends(require(spk_service.WRITE)),
    db: Session = Depends(get_db),
) -> schemas.SpkOut:
    return _spk_out(db, ctx, spk_service.update(db, ctx, spk_id, payload))


@spk_router.post(
    "/{spk_id}/transitions/{action}",
    response_model=schemas.SpkOut,
    summary="submit / withdraw / approve / reject / reopen",
)
def spk_transition(
    spk_id: uuid.UUID,
    action: Action,
    payload: TransitionIn,
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> schemas.SpkOut:
    return _spk_out(db, ctx, spk_service.transition(db, ctx, spk_id, action, payload.note))


@spk_router.get(
    "/{spk_id}/progress",
    response_model=schemas.SpkProgress,
    summary="Item kontrak dan volume yang sudah diserahterimakan",
)
def spk_progress(
    spk_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> schemas.SpkProgress:
    spk = spk_service.get(db, ctx, spk_id)
    final = bast_service.final_of(db, ctx, spk.id)
    return schemas.SpkProgress(
        spk_id=spk.id,
        items=[
            schemas.ContractItemProgress(
                rab_item_id=row.item.id,
                no=row.no,
                code=row.item.code,
                name=row.item.name,
                category=row.item.category,
                unit=row.item.unit,
                contract_quantity=row.item.quantity,
                delivered_quantity=row.delivered,
                pending_quantity=row.pending,
                remaining_quantity=row.remaining,
            )
            for row in progress.progress(db, ctx, spk)
        ],
        final_bast=RefBrief(id=final.id, number=final.number) if final else None,
    )


@spk_router.get(
    "/{spk_id}/preview.pdf",
    response_class=Response,
    summary="Pratinjau PDF",
    dependencies=EXPENSIVE,
)
def spk_preview(
    spk_id: uuid.UUID,
    download: bool = Query(False),
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> Response:
    return file_response(spk_service.preview_pdf(db, ctx, spk_id), inline=not download)


@spk_router.post(
    "/{spk_id}/issue",
    dependencies=EXPENSIVE,
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Terbitkan SPK (nomor, snapshot + PDF); idempoten dengan Idempotency-Key",
)
def issue_spk(
    spk_id: uuid.UUID,
    response: Response,
    idempotency_key: IdempotencyKey = None,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> DocumentOut:
    issued = spk_service.issue(db, ctx, spk_id, idempotency_key)
    if not issued.created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return DocumentOut.model_validate(issued.document)


@spk_router.post("/{spk_id}/void", response_model=schemas.SpkOut, summary="Batalkan SPK terbit")
def void_spk(
    spk_id: uuid.UUID,
    payload: VoidIn,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> schemas.SpkOut:
    return _spk_out(db, ctx, spk_service.void(db, ctx, spk_id, payload.reason))


@spk_router.delete(
    "/{spk_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Hapus SPK draft/ditolak"
)
def delete_spk(
    spk_id: uuid.UUID,
    ctx: RequestContext = Depends(require(spk_service.WRITE)),
    db: Session = Depends(get_db),
) -> Response:
    spk_service.delete(db, ctx, spk_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- BAST mapping


def _bast_item(bast: Bast, item_count: int) -> dict[str, Any]:
    spk = bast.spk
    return {
        "id": bast.id,
        "number": bast.number,
        "status": bast.status,
        "kind": bast.kind,
        "title": bast.title,
        "spk": RefBrief(id=spk.id, number=spk.number),
        "project": _project_brief(spk),
        "client": _client_brief(spk),
        "handover_date": bast.handover_date,
        "item_count": item_count,
        "created_at": bast.created_at,
        "updated_at": bast.updated_at,
    }


def _bast_out(db: Session, ctx: RequestContext, bast: Bast) -> schemas.BastOut:
    return schemas.BastOut(
        **_bast_item(bast, len(bast.items)),
        location=bast.location,
        delivered_by_name=bast.delivered_by_name,
        delivered_by_title=bast.delivered_by_title,
        received_by_name=bast.received_by_name,
        received_by_title=bast.received_by_title,
        terms=bast.terms,
        notes=bast.notes,
        items=[schemas.BastItemOut.model_validate(i) for i in bast.items],
        submitted_by=_user(bast.submitted_by),
        submitted_at=bast.submitted_at,
        decided_by=_user(bast.decided_by),
        decided_at=bast.decided_at,
        voided_at=bast.voided_at,
        void_reason=bast.void_reason,
        version=bast.version,
        approvals=_approvals(db, ctx, bast_service.ENTITY, bast.id),
        allowed_actions=[
            a.value for a in allowed_actions(bast.status, ctx.permissions, write=bast_service.WRITE)
        ],
        editable=bast.status is DocStatus.DRAFT and ctx.can(bast_service.WRITE),
        can_issue=bast.status is DocStatus.APPROVED and ctx.can(P.DOCUMENTS_ISSUE),
        can_void=bast.status is DocStatus.ISSUED and ctx.can(P.DOCUMENTS_ISSUE),
        can_delete=bast.status in DELETABLE and ctx.can(bast_service.WRITE),
    )


@bast_router.get("", response_model=Page[schemas.BastListItem], summary="Daftar BAST")
def list_bast(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100),
    status_: DocStatus | None = Query(None, alias="status"),
    kind: BastKind | None = Query(None),
    spk_id: uuid.UUID | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    sort: str | None = Query(None, description="created_at, number, handover_date; awali '-'"),
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> Page[schemas.BastListItem]:
    items, total = bast_service.list_bast(
        db,
        ctx,
        params,
        q=q,
        status=status_,
        kind=kind,
        spk_id=spk_id,
        project_id=project_id,
        sort=sort,
    )
    counts = bast_service.item_counts(db, ctx, [x.id for x in items])
    return Page(
        items=[schemas.BastListItem(**_bast_item(x, counts.get(x.id, 0))) for x in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@bast_router.post(
    "",
    response_model=schemas.BastOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat BAST untuk SPK terbit",
)
def create_bast(
    payload: schemas.BastCreate,
    ctx: RequestContext = Depends(require(bast_service.WRITE)),
    db: Session = Depends(get_db),
) -> schemas.BastOut:
    return _bast_out(db, ctx, bast_service.create(db, ctx, payload))


@bast_router.get("/{bast_id}", response_model=schemas.BastOut, summary="Detail BAST")
def get_bast(
    bast_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> schemas.BastOut:
    return _bast_out(db, ctx, bast_service.get(db, ctx, bast_id))


@bast_router.patch(
    "/{bast_id}", response_model=schemas.BastOut, summary="Ubah BAST dan barisnya (draft)"
)
def update_bast(
    bast_id: uuid.UUID,
    payload: schemas.BastUpdate,
    ctx: RequestContext = Depends(require(bast_service.WRITE)),
    db: Session = Depends(get_db),
) -> schemas.BastOut:
    return _bast_out(db, ctx, bast_service.update(db, ctx, bast_id, payload))


@bast_router.post(
    "/{bast_id}/transitions/{action}",
    response_model=schemas.BastOut,
    summary="submit / withdraw / approve / reject / reopen",
)
def bast_transition(
    bast_id: uuid.UUID,
    action: Action,
    payload: TransitionIn,
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> schemas.BastOut:
    return _bast_out(db, ctx, bast_service.transition(db, ctx, bast_id, action, payload.note))


@bast_router.get(
    "/{bast_id}/preview.pdf",
    response_class=Response,
    summary="Pratinjau PDF",
    dependencies=EXPENSIVE,
)
def bast_preview(
    bast_id: uuid.UUID,
    download: bool = Query(False),
    ctx: RequestContext = Depends(require(P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> Response:
    return file_response(bast_service.preview_pdf(db, ctx, bast_id), inline=not download)


@bast_router.post(
    "/{bast_id}/issue",
    dependencies=EXPENSIVE,
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Terbitkan BAST (nomor, snapshot + PDF); idempoten dengan Idempotency-Key",
)
def issue_bast(
    bast_id: uuid.UUID,
    response: Response,
    idempotency_key: IdempotencyKey = None,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> DocumentOut:
    issued = bast_service.issue(db, ctx, bast_id, idempotency_key)
    if not issued.created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return DocumentOut.model_validate(issued.document)


@bast_router.post("/{bast_id}/void", response_model=schemas.BastOut, summary="Batalkan BAST terbit")
def void_bast(
    bast_id: uuid.UUID,
    payload: VoidIn,
    ctx: RequestContext = Depends(require(P.DOCUMENTS_ISSUE)),
    db: Session = Depends(get_db),
) -> schemas.BastOut:
    return _bast_out(db, ctx, bast_service.void(db, ctx, bast_id, payload.reason))


@bast_router.delete(
    "/{bast_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Hapus BAST draft/ditolak"
)
def delete_bast(
    bast_id: uuid.UUID,
    ctx: RequestContext = Depends(require(bast_service.WRITE)),
    db: Session = Depends(get_db),
) -> Response:
    bast_service.delete(db, ctx, bast_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
