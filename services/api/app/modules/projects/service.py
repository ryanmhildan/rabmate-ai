from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.core.pagination import PageParams, apply_sort, escape_like, paginate
from app.modules.audit import service as audit
from app.modules.clients.models import Client
from app.modules.identity.service import require_member_user
from app.modules.numbering.service import format_number, next_value
from app.modules.projects.lifecycle import allowed_transitions, can_transition
from app.modules.projects.models import Project, ProjectMember, ProjectStatus, ProjectType
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectMembersUpdate,
    ProjectUpdate,
    check_dates,
    check_tax,
)
from app.modules.rab.models import RabDocument
from app.shared.concurrency import check_version

AUDITED_FIELDS = (
    "number",
    "name",
    "project_type",
    "client_id",
    "description",
    "scope",
    "location",
    "start_date",
    "end_date",
    "status",
    "currency",
    "tax_label",
    "tax_rate_percent",
    "budget_amount",
    "notes",
    "attributes",
    "owner_id",
)

SORTABLE = {
    "number": Project.number,
    "name": Project.name,
    "status": Project.status,
    "start_date": Project.start_date,
    "created_at": Project.created_at,
    "updated_at": Project.updated_at,
}

NUMBER_KIND = "project"
NUMBER_PREFIX = "PRJ"


def get_project(db: Session, ctx: RequestContext, project_id: uuid.UUID) -> Project:
    project = db.execute(
        select(Project).where(
            Project.id == project_id, Project.organization_id == ctx.organization_id
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Proyek tidak ditemukan.")
    return project


def list_projects(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    status: ProjectStatus | None,
    project_type: ProjectType | None,
    client_id: uuid.UUID | None,
    sort: str | None,
) -> tuple[list[Project], int]:
    stmt = (
        select(Project)
        .outerjoin(
            Client,
            (Client.id == Project.client_id) & (Client.organization_id == Project.organization_id),
        )
        .where(Project.organization_id == ctx.organization_id)
    )
    if q:
        term = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(
                Project.name.ilike(term, escape="\\"),
                Project.number.ilike(term, escape="\\"),
                Project.location.ilike(term, escape="\\"),
                Client.name.ilike(term, escape="\\"),
            )
        )
    if status is not None:
        stmt = stmt.where(Project.status == status)
    if project_type is not None:
        stmt = stmt.where(Project.project_type == project_type)
    if client_id is not None:
        stmt = stmt.where(Project.client_id == client_id)
    stmt = apply_sort(stmt, sort, SORTABLE, default="-created_at")
    return paginate(db, stmt, params)


def _require_client(db: Session, ctx: RequestContext, client_id: uuid.UUID) -> Client:
    client = db.execute(
        select(Client).where(Client.id == client_id, Client.organization_id == ctx.organization_id)
    ).scalar_one_or_none()
    if client is None:
        # Same message whether the client is missing or belongs to another organization.
        raise BusinessValidationError(
            "Klien tidak ditemukan.", details=[{"loc": ["body", "client_id"]}]
        )
    return client


def _current_year() -> int:
    return datetime.now(ZoneInfo(get_settings().timezone)).year


def create_project(db: Session, ctx: RequestContext, payload: ProjectCreate) -> Project:
    if payload.client_id is not None:
        _require_client(db, ctx, payload.client_id)
    if payload.owner_id is not None:
        require_member_user(db, ctx, payload.owner_id)

    data = payload.model_dump(exclude={"number"})
    number = payload.number
    if number is None:
        year = _current_year()
        number = format_number(
            NUMBER_PREFIX, year, next_value(db, ctx.organization_id, NUMBER_KIND, year)
        )

    project = Project(
        organization_id=ctx.organization_id,
        created_by_id=ctx.user_id,
        number=number,
        **data,
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if "uq_projects_organization_id_number" in str(exc.orig):
            raise ConflictError("Nomor proyek sudah dipakai.") from None
        raise
    after = audit.snapshot(project, AUDITED_FIELDS)
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="project.create",
        entity_type="project",
        entity_id=project.id,
        summary=f"{project.number} {project.name}",
        changes={k: {"from": None, "to": v} for k, v in after.items() if v not in (None, {})},
        ip_address=ctx.ip_address,
    )
    db.commit()
    db.refresh(project)
    return project


def update_project(
    db: Session, ctx: RequestContext, project_id: uuid.UUID, payload: ProjectUpdate
) -> Project:
    project = get_project(db, ctx, project_id)
    check_version(project.version, payload.version)
    data: dict[str, Any] = payload.model_dump(exclude_unset=True, exclude={"version"})

    for field in ("name", "project_type", "status", "currency", "attributes"):
        if field in data and data[field] is None:
            raise BusinessValidationError(f"Field {field} tidak boleh kosong.")
    if data.get("client_id") is not None:
        _require_client(db, ctx, data["client_id"])
    if data.get("owner_id") is not None:
        require_member_user(db, ctx, data["owner_id"])
    new_status = data.get("status")
    if new_status is not None and not can_transition(project.status, new_status):
        raise BusinessValidationError(
            f"Status tidak dapat diubah dari '{project.status.value}' ke '{new_status.value}'.",
            details={"allowed": [s.value for s in allowed_transitions(project.status)]},
        )

    # Cross-field rules evaluated on the merged result, not just the patch.
    try:
        check_dates(
            data.get("start_date", project.start_date), data.get("end_date", project.end_date)
        )
        check_tax(
            data.get("tax_label", project.tax_label),
            data.get("tax_rate_percent", project.tax_rate_percent),
        )
    except ValueError as exc:
        raise BusinessValidationError(str(exc)) from None

    before = audit.snapshot(project, AUDITED_FIELDS)
    for field, value in data.items():
        setattr(project, field, value)
    changes = audit.diff(before, audit.snapshot(project, AUDITED_FIELDS))
    if not changes:
        return project

    db.flush()
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="project.status_change" if set(changes) == {"status"} else "project.update",
        entity_type="project",
        entity_id=project.id,
        summary=f"{project.number} {project.name}",
        changes=changes,
        ip_address=ctx.ip_address,
    )
    db.commit()
    db.refresh(project)
    return project


def set_members(
    db: Session, ctx: RequestContext, project_id: uuid.UUID, payload: ProjectMembersUpdate
) -> Project:
    project = get_project(db, ctx, project_id)
    wanted = {m.user_id: m.role for m in payload.members}
    if len(wanted) != len(payload.members):
        raise BusinessValidationError("Pengguna yang sama tercantum lebih dari sekali.")
    for user_id in wanted:
        require_member_user(db, ctx, user_id)

    before = {str(m.user_id): m.role.value for m in project.members}
    # Update in place: re-creating rows with the same primary key would clash in the session.
    for member in list(project.members):
        if member.user_id not in wanted:
            project.members.remove(member)
        else:
            member.role = wanted.pop(member.user_id)
    for user_id, role in wanted.items():
        project.members.append(ProjectMember(project_id=project.id, user_id=user_id, role=role))
    after = {str(m.user_id): m.role.value for m in project.members}
    if before != after:
        # Touch the project so its version moves and concurrent editors notice.
        project.updated_at = datetime.now(ZoneInfo("UTC"))
        audit.record(
            db,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action="project.members_update",
            entity_type="project",
            entity_id=project.id,
            summary=f"{project.number} {project.name}",
            changes={"members": {"from": before, "to": after}},
            ip_address=ctx.ip_address,
        )
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, ctx: RequestContext, project_id: uuid.UUID) -> None:
    project = get_project(db, ctx, project_id)
    has_rab = db.execute(
        select(
            exists().where(
                RabDocument.organization_id == ctx.organization_id,
                RabDocument.project_id == project.id,
            )
        )
    ).scalar_one()
    if has_rab:
        raise ConflictError(
            "Proyek masih memiliki RAB. Hapus RAB-nya atau batalkan proyek sebagai gantinya."
        )
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="project.delete",
        entity_type="project",
        entity_id=project.id,
        summary=f"{project.number} {project.name}",
        ip_address=ctx.ip_address,
    )
    db.delete(project)
    db.commit()
