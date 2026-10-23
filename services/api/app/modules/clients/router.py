from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.clients import service
from app.modules.clients.schemas import ClientCreate, ClientOut, ClientUpdate
from app.modules.identity.permissions import Permission

router = APIRouter(
    prefix="/clients",
    tags=["clients"],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)


@router.get("", response_model=Page[ClientOut], summary="Daftar klien")
def list_clients(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100, description="Cari nama, kode, kontak, kota"),
    is_active: bool | None = Query(None),
    sort: str | None = Query(None, description="name, code, created_at, updated_at; awali '-'"),
    ctx: RequestContext = Depends(require(Permission.CLIENTS_READ)),
    db: Session = Depends(get_db),
) -> Page[ClientOut]:
    items, total = service.list_clients(db, ctx, params, q=q, is_active=is_active, sort=sort)
    return Page[ClientOut](
        items=[ClientOut.model_validate(c) for c in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post(
    "", response_model=ClientOut, status_code=status.HTTP_201_CREATED, summary="Tambah klien"
)
def create_client(
    payload: ClientCreate,
    ctx: RequestContext = Depends(require(Permission.CLIENTS_WRITE)),
    db: Session = Depends(get_db),
) -> ClientOut:
    return ClientOut.model_validate(service.create_client(db, ctx, payload))


@router.get("/{client_id}", response_model=ClientOut, summary="Detail klien")
def get_client(
    client_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.CLIENTS_READ)),
    db: Session = Depends(get_db),
) -> ClientOut:
    return ClientOut.model_validate(service.get_client(db, ctx, client_id))


@router.patch("/{client_id}", response_model=ClientOut, summary="Ubah klien")
def update_client(
    client_id: uuid.UUID,
    payload: ClientUpdate,
    ctx: RequestContext = Depends(require(Permission.CLIENTS_WRITE)),
    db: Session = Depends(get_db),
) -> ClientOut:
    return ClientOut.model_validate(service.update_client(db, ctx, client_id, payload))


@router.delete(
    "/{client_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Hapus klien (jika tak dipakai)"
)
def delete_client(
    client_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.CLIENTS_DELETE)),
    db: Session = Depends(get_db),
) -> Response:
    service.delete_client(db, ctx, client_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
