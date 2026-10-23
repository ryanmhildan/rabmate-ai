from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, page_params
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.projects import service
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectListItem,
    ProjectMembersUpdate,
    ProjectOut,
    ProjectUpdate,
)

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)


def _out(project: Project) -> ProjectOut:
    return ProjectOut.model_validate(project)


@router.get("", response_model=Page[ProjectListItem], summary="Daftar proyek")
def list_projects(
    params: PageParams = Depends(page_params),
    q: str | None = Query(None, max_length=100, description="Cari nomor, nama, lokasi, klien"),
    status_filter: ProjectStatus | None = Query(None, alias="status"),
    project_type: ProjectType | None = Query(None),
    client_id: uuid.UUID | None = Query(None),
    sort: str | None = Query(
        None, description="number, name, status, start_date, created_at, updated_at; awali '-'"
    ),
    ctx: RequestContext = Depends(require(Permission.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> Page[ProjectListItem]:
    items, total = service.list_projects(
        db,
        ctx,
        params,
        q=q,
        status=status_filter,
        project_type=project_type,
        client_id=client_id,
        sort=sort,
    )
    return Page[ProjectListItem](
        items=[ProjectListItem.model_validate(p) for p in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post(
    "", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, summary="Buat proyek"
)
def create_project(
    payload: ProjectCreate,
    ctx: RequestContext = Depends(require(Permission.PROJECTS_WRITE)),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return _out(service.create_project(db, ctx, payload))


@router.get("/{project_id}", response_model=ProjectOut, summary="Detail proyek")
def get_project(
    project_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return _out(service.get_project(db, ctx, project_id))


@router.patch("/{project_id}", response_model=ProjectOut, summary="Ubah proyek")
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    ctx: RequestContext = Depends(require(Permission.PROJECTS_WRITE)),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return _out(service.update_project(db, ctx, project_id, payload))


@router.put("/{project_id}/members", response_model=ProjectOut, summary="Atur anggota proyek")
def set_members(
    project_id: uuid.UUID,
    payload: ProjectMembersUpdate,
    ctx: RequestContext = Depends(require(Permission.PROJECTS_WRITE)),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return _out(service.set_members(db, ctx, project_id, payload))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Hapus proyek")
def delete_project(
    project_id: uuid.UUID,
    ctx: RequestContext = Depends(require(Permission.PROJECTS_DELETE)),
    db: Session = Depends(get_db),
) -> Response:
    service.delete_project(db, ctx, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
