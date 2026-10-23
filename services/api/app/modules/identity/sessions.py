from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_token, new_token
from app.modules.identity.models import UserSession

# Avoid a write on every request: refresh last_seen_at at most this often.
_TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class IssuedSession:
    session: UserSession
    token: str
    csrf_token: str


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_session(
    db: Session,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    settings: Settings,
    ip_address: str | None,
    user_agent: str | None,
    now: datetime | None = None,
) -> IssuedSession:
    now = now or utcnow()
    token, csrf_token = new_token(), new_token()
    session = UserSession(
        user_id=user_id,
        organization_id=organization_id,
        token_hash=hash_token(token),
        csrf_token_hash=hash_token(csrf_token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_max_age_hours),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    return IssuedSession(session=session, token=token, csrf_token=csrf_token)


def resolve_session(
    db: Session, token: str, settings: Settings, now: datetime | None = None
) -> UserSession | None:
    """Returns the live session for a cookie token, or None if unknown/expired/idle/revoked."""
    now = now or utcnow()
    session = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return None
    idle_limit = timedelta(minutes=settings.session_idle_timeout_minutes)
    if now >= session.expires_at or now - session.last_seen_at >= idle_limit:
        return None
    if now - session.last_seen_at >= _TOUCH_INTERVAL:
        session.last_seen_at = now
    return session


def revoke_session(session: UserSession, now: datetime | None = None) -> None:
    session.revoked_at = now or utcnow()


def revoke_user_sessions(
    db: Session,
    user_id: uuid.UUID,
    *,
    organization_id: uuid.UUID | None = None,
    except_session_id: uuid.UUID | None = None,
) -> None:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    if organization_id is not None:
        stmt = stmt.where(UserSession.organization_id == organization_id)
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    db.execute(stmt)
