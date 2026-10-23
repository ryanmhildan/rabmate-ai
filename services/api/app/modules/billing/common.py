"""Small helpers shared by the quotation, invoice and payment services."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import BusinessValidationError, ConflictError, PermissionDeniedError
from app.modules.approvals.models import ApprovalRecord
from app.modules.audit import service as audit
from app.modules.billing.models import DocStatus, WorkflowColumns
from app.modules.billing.workflow import TRANSITIONS, Action
from app.modules.identity.permissions import Permission

JAKARTA = ZoneInfo("Asia/Jakarta")


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    """Business date in Asia/Jakarta (due dates, overdue, issue dates)."""
    return datetime.now(JAKARTA).date()


def record_audit(
    db: Session,
    ctx: RequestContext,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    summary: str,
    changes: Mapping[str, Any] | None = None,
) -> None:
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        changes=dict(changes) if changes is not None else None,
        ip_address=ctx.ip_address,
    )


def approvals_of(
    db: Session, ctx: RequestContext, entity_type: str, entity_id: uuid.UUID
) -> list[ApprovalRecord]:
    return list(
        db.execute(
            select(ApprovalRecord)
            .where(
                ApprovalRecord.organization_id == ctx.organization_id,
                ApprovalRecord.entity_type == entity_type,
                ApprovalRecord.entity_id == entity_id,
            )
            .order_by(ApprovalRecord.created_at)
        ).scalars()
    )


def apply_transition(
    db: Session,
    ctx: RequestContext,
    entity: WorkflowColumns,
    entity_type: str,
    action: Action,
    note: str | None,
    *,
    write: Permission,
) -> DocStatus:
    """Checks status + permission for `action`, moves the status, and records the decision."""
    transition = TRANSITIONS[action]
    needed = Permission.DOCUMENTS_APPROVE if transition.approval else write
    if not ctx.can(needed):
        raise PermissionDeniedError()
    if entity.status not in transition.sources:
        raise ConflictError(
            "Aksi tidak tersedia untuk status saat ini.",
            details={"status": entity.status.value, "action": action.value},
        )
    if transition.note_required and not note:
        raise BusinessValidationError(
            "Alasan wajib diisi.", details=[{"loc": ["body", "note"], "msg": "Wajib diisi."}]
        )
    before = entity.status
    entity.status = transition.target
    moment = now()
    if action is Action.SUBMIT:
        entity.submitted_at = moment
        entity.submitted_by_id = ctx.user_id
    elif action in (Action.APPROVE, Action.REJECT):
        entity.decided_at = moment
        entity.decided_by_id = ctx.user_id
    elif action is Action.REOPEN:
        entity.decided_at = None
        entity.decided_by_id = None
    db.add(
        ApprovalRecord(
            organization_id=ctx.organization_id,
            entity_type=entity_type,
            entity_id=entity.id,
            action=transition.record,
            from_status=before.value,
            to_status=transition.target.value,
            actor_user_id=ctx.user_id,
            note=note,
        )
    )
    return before
