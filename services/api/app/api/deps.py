"""Request authentication, CSRF verification and permission checks.

Every authenticated endpoint depends on `require(...)`, which yields a RequestContext scoped to
the session's active organization. Services receive the context and must filter every query by
`ctx.organization_id` — including detail, update, delete and download paths.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, CsrfError, PermissionDeniedError
from app.core.security import tokens_match
from app.db.session import get_db
from app.modules.identity.models import Membership, Organization, User, UserSession
from app.modules.identity.permissions import Permission, Role, permissions_for
from app.modules.identity.sessions import resolve_session, revoke_session

SESSION_COOKIE = "rabmate_session"
CSRF_COOKIE = "rabmate_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class RequestContext:
    user: User
    organization: Organization
    membership: Membership
    session: UserSession
    permissions: frozenset[Permission]
    ip_address: str | None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def organization_id(self) -> uuid.UUID:
        return self.organization.id

    @property
    def role(self) -> Role:
        return self.membership.role

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        if permission not in self.permissions:
            raise PermissionDeniedError()


def client_ip(request: Request, settings: Settings) -> str | None:
    peer = request.client.host if request.client else None
    if peer in settings.trusted_proxy_ips:
        forwarded = request.headers.get("x-forwarded-for", "")
        # Rightmost entry is the one appended by our trusted proxy.
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1][:45]
    return peer


def get_context(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RequestContext:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthenticationError()
    session = resolve_session(db, token, settings)
    if session is None:
        raise AuthenticationError("Sesi Anda telah berakhir. Silakan masuk kembali.")

    if request.method not in SAFE_METHODS:
        csrf = request.headers.get(CSRF_HEADER, "")
        if not csrf or not tokens_match(csrf, session.csrf_token_hash):
            raise CsrfError()

    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == session.organization_id,
            Membership.user_id == session.user_id,
        )
    ).scalar_one_or_none()
    if membership is None or not membership.is_active or not membership.user.is_active:
        revoke_session(session)
        db.commit()
        raise AuthenticationError("Akun Anda tidak aktif di organisasi ini.")

    # Persist a refreshed last_seen_at (resolve_session only touches it every few minutes).
    if db.is_modified(session):
        db.commit()

    return RequestContext(
        user=membership.user,
        organization=membership.organization,
        membership=membership,
        session=session,
        permissions=permissions_for(membership.role),
        ip_address=client_ip(request, settings),
    )


def require(*permissions: Permission) -> Callable[..., RequestContext]:
    """Dependency factory: authenticated context that holds all given permissions."""

    def dependency(ctx: RequestContext = Depends(get_context)) -> RequestContext:
        for permission in permissions:
            ctx.require(permission)
        return ctx

    return dependency
