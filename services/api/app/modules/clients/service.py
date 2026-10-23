from __future__ import annotations

import uuid

from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.core.pagination import PageParams, apply_sort, escape_like, paginate
from app.modules.audit import service as audit
from app.modules.clients.models import Client
from app.modules.clients.schemas import ClientCreate, ClientUpdate
from app.modules.projects.models import Project
from app.shared.concurrency import check_version

AUDITED_FIELDS = (
    "code",
    "name",
    "client_type",
    "tax_id",
    "email",
    "phone",
    "address",
    "city",
    "contact_person",
    "notes",
    "is_active",
)

SORTABLE = {
    "name": Client.name,
    "code": Client.code,
    "created_at": Client.created_at,
    "updated_at": Client.updated_at,
}


def get_client(db: Session, ctx: RequestContext, client_id: uuid.UUID) -> Client:
    client = db.execute(
        select(Client).where(Client.id == client_id, Client.organization_id == ctx.organization_id)
    ).scalar_one_or_none()
    if client is None:
        raise NotFoundError("Klien tidak ditemukan.")
    return client


def list_clients(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    is_active: bool | None,
    sort: str | None,
) -> tuple[list[Client], int]:
    stmt = select(Client).where(Client.organization_id == ctx.organization_id)
    if q:
        term = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(
                Client.name.ilike(term, escape="\\"),
                Client.code.ilike(term, escape="\\"),
                Client.contact_person.ilike(term, escape="\\"),
                Client.city.ilike(term, escape="\\"),
            )
        )
    if is_active is not None:
        stmt = stmt.where(Client.is_active.is_(is_active))
    stmt = apply_sort(stmt, sort, SORTABLE, default="name")
    return paginate(db, stmt, params)


def _duplicate_code(exc: IntegrityError) -> bool:
    return "uq_clients_organization_id_code" in str(exc.orig)


def create_client(db: Session, ctx: RequestContext, payload: ClientCreate) -> Client:
    client = Client(
        organization_id=ctx.organization_id, created_by_id=ctx.user_id, **payload.model_dump()
    )
    db.add(client)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _duplicate_code(exc):
            raise ConflictError("Kode klien sudah dipakai.") from None
        raise
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="client.create",
        entity_type="client",
        entity_id=client.id,
        summary=client.name,
        changes={
            k: {"from": None, "to": v}
            for k, v in audit.snapshot(client, AUDITED_FIELDS).items()
            if v is not None
        },
        ip_address=ctx.ip_address,
    )
    db.commit()
    db.refresh(client)
    return client


def update_client(
    db: Session, ctx: RequestContext, client_id: uuid.UUID, payload: ClientUpdate
) -> Client:
    client = get_client(db, ctx, client_id)
    check_version(client.version, payload.version)
    before = audit.snapshot(client, AUDITED_FIELDS)

    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    for field in ("name", "client_type", "is_active"):
        if field in data and data[field] is None:
            raise BusinessValidationError(f"Field {field} tidak boleh kosong.")
    for field, value in data.items():
        setattr(client, field, value)

    changes = audit.diff(before, audit.snapshot(client, AUDITED_FIELDS))
    if not changes:
        return client
    try:
        db.flush()  # bumps version; raises StaleDataError if someone else committed first
    except IntegrityError as exc:
        db.rollback()
        if _duplicate_code(exc):
            raise ConflictError("Kode klien sudah dipakai.") from None
        raise
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="client.update",
        entity_type="client",
        entity_id=client.id,
        summary=client.name,
        changes=changes,
        ip_address=ctx.ip_address,
    )
    db.commit()
    db.refresh(client)
    return client


def delete_client(db: Session, ctx: RequestContext, client_id: uuid.UUID) -> None:
    client = get_client(db, ctx, client_id)
    referenced = db.execute(
        select(
            exists().where(
                Project.organization_id == ctx.organization_id, Project.client_id == client.id
            )
        )
    ).scalar_one()
    if referenced:
        raise ConflictError("Klien masih dipakai oleh proyek. Nonaktifkan klien sebagai gantinya.")
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="client.delete",
        entity_type="client",
        entity_id=client.id,
        summary=client.name,
        ip_address=ctx.ip_address,
    )
    db.delete(client)
    db.commit()
