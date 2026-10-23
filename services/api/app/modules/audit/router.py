from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, require
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParams, count_rows, page_params
from app.db.session import get_db
from app.modules.audit.models import AuditLog
from app.modules.identity.models import User
from app.modules.identity.permissions import Permission

router = APIRouter(
    prefix="/audit-logs",
    tags=["audit"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


class AuditActor(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class AuditLogOut(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    summary: str | None
    changes: dict[str, Any] | None
    actor: AuditActor | None
    created_at: datetime


def recent_entries(db: Session, organization_id: uuid.UUID, limit: int) -> list[AuditLogOut]:
    stmt = _base_query(organization_id).order_by(AuditLog.created_at.desc()).limit(limit)
    return [_to_out(log, user) for log, user in db.execute(stmt).all()]


def _base_query(organization_id: uuid.UUID) -> Select[AuditLog, User]:
    return (
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.organization_id == organization_id)
    )


def _to_out(log: AuditLog, user: User | None) -> AuditLogOut:
    return AuditLogOut(
        id=log.id,
        action=log.action,
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        summary=log.summary,
        changes=log.changes,
        actor=AuditActor(id=user.id, full_name=user.full_name, email=user.email) if user else None,
        created_at=log.created_at,
    )


@router.get("", response_model=Page[AuditLogOut], summary="Riwayat aktivitas organisasi")
def list_audit_logs(
    params: PageParams = Depends(page_params),
    entity_type: str | None = Query(None, max_length=64),
    entity_id: uuid.UUID | None = Query(None),
    actor_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None, max_length=64),
    ctx: RequestContext = Depends(require(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> Page[AuditLogOut]:
    stmt = _base_query(ctx.organization_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)

    total = count_rows(db, stmt)
    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id)
        .limit(params.page_size)
        .offset(params.offset)
    ).all()
    return Page[AuditLogOut](
        items=[_to_out(log, user) for log, user in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
