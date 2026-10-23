from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.modules.audit.models import AuditLog

# Never written to audit logs, even if a caller passes them in a diff.
_FORBIDDEN_FIELDS = frozenset(
    {"password", "password_hash", "token", "token_hash", "csrf_token_hash"}
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def snapshot(obj: Any, fields: Iterable[str]) -> dict[str, Any]:
    return {field: _jsonable(getattr(obj, field)) for field in fields}


def diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """{field: {"from": old, "to": new}} for fields whose value changed."""
    return {
        field: {"from": before.get(field), "to": after.get(field)}
        for field in after
        if field not in _FORBIDDEN_FIELDS and before.get(field) != after.get(field)
    }


def record(
    db: Session,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: str | None = None,
    changes: Mapping[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Adds an audit entry to the caller's transaction (commits with the change it describes)."""
    clean = (
        {k: _jsonable(v) for k, v in changes.items() if k not in _FORBIDDEN_FIELDS}
        if changes
        else None
    )
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary[:300] if summary else None,
        changes=clean or None,
        ip_address=ip_address,
        request_id=request_id_var.get(),
    )
    db.add(entry)
    return entry
