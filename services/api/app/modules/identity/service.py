from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.config import Settings
from app.core.errors import (
    BusinessValidationError,
    ConflictError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
)
from app.core.security import (
    burn_password_check,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.modules.audit import service as audit
from app.modules.identity.models import LoginAttempt, Membership, Organization, User
from app.modules.identity.permissions import Role
from app.modules.identity.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MemberCreate,
    MemberUpdate,
    OrganizationUpdate,
)
from app.modules.identity.sessions import (
    IssuedSession,
    create_session,
    revoke_session,
    revoke_user_sessions,
    utcnow,
)

ORG_FIELDS = ("name", "legal_name", "tax_id", "email", "phone", "address", "city", "website")


# --------------------------------------------------------------------------- login


def _check_throttle(
    db: Session, email: str, ip: str | None, settings: Settings, now: datetime
) -> None:
    since = now - timedelta(minutes=settings.login_window_minutes)
    failures = (
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.succeeded.is_(False), LoginAttempt.created_at > since)
    )
    by_email = db.execute(failures.where(LoginAttempt.email == email)).scalar_one()
    by_ip = db.execute(failures.where(LoginAttempt.ip_address == ip)).scalar_one() if ip else 0
    if (
        by_email >= settings.login_max_failures_per_email
        or by_ip >= settings.login_max_failures_per_ip
    ):
        raise RateLimitedError(
            "Terlalu banyak percobaan masuk yang gagal. Coba lagi beberapa menit lagi.",
            headers={"Retry-After": str(settings.login_window_minutes * 60)},
        )


def _record_attempt(
    db: Session, email: str, ip: str | None, succeeded: bool, now: datetime
) -> None:
    db.add(LoginAttempt(email=email, ip_address=ip, succeeded=succeeded, created_at=now))


def _fail_login(db: Session, email: str, ip: str | None, now: datetime) -> InvalidCredentialsError:
    _record_attempt(db, email, ip, False, now)
    db.commit()  # the failed attempt must persist even though the request errors
    return InvalidCredentialsError()


def active_memberships(db: Session, user_id: uuid.UUID) -> list[Membership]:
    return list(
        db.execute(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.is_active.is_(True))
            .order_by(Membership.created_at)
        ).scalars()
    )


@dataclass(frozen=True)
class LoginResult:
    issued: IssuedSession
    membership: Membership


def login(
    db: Session,
    payload: LoginRequest,
    *,
    settings: Settings,
    ip: str | None,
    user_agent: str | None,
    now: datetime | None = None,
) -> LoginResult:
    now = now or utcnow()
    email = payload.email
    _check_throttle(db, email, ip, settings, now)

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active:
        burn_password_check(payload.password)
        raise _fail_login(db, email, ip, now)
    if not verify_password(user.password_hash, payload.password):
        raise _fail_login(db, email, ip, now)

    memberships = active_memberships(db, user.id)
    if payload.organization_id is not None:
        memberships = [m for m in memberships if m.organization_id == payload.organization_id]
    if not memberships:
        raise _fail_login(db, email, ip, now)
    membership = memberships[0]

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = now

    issued = create_session(
        db,
        user_id=user.id,
        organization_id=membership.organization_id,
        settings=settings,
        ip_address=ip,
        user_agent=user_agent,
        now=now,
    )
    _record_attempt(db, email, ip, True, now)
    audit.record(
        db,
        organization_id=membership.organization_id,
        actor_user_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        summary=user.email,
        ip_address=ip,
    )
    db.commit()
    return LoginResult(issued=issued, membership=membership)


def logout(db: Session, ctx: RequestContext) -> None:
    revoke_session(ctx.session)
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="auth.logout",
        entity_type="user",
        entity_id=ctx.user_id,
        summary=ctx.user.email,
        ip_address=ctx.ip_address,
    )
    db.commit()


def change_password(db: Session, ctx: RequestContext, payload: ChangePasswordRequest) -> None:
    if not verify_password(ctx.user.password_hash, payload.current_password):
        raise BusinessValidationError(
            "Kata sandi saat ini salah.", details=[{"loc": ["body", "current_password"]}]
        )
    if payload.current_password == payload.new_password:
        raise BusinessValidationError("Kata sandi baru harus berbeda dari kata sandi lama.")
    ctx.user.password_hash = hash_password(payload.new_password)
    # Every other session (other browsers, other organizations) must log in again.
    revoke_user_sessions(db, ctx.user_id, except_session_id=ctx.session.id)
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="auth.password_changed",
        entity_type="user",
        entity_id=ctx.user_id,
        summary=ctx.user.email,
        ip_address=ctx.ip_address,
    )
    db.commit()


def switch_organization(db: Session, ctx: RequestContext, organization_id: uuid.UUID) -> Membership:
    membership = db.execute(
        select(Membership).where(
            Membership.user_id == ctx.user_id,
            Membership.organization_id == organization_id,
            Membership.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Organisasi tidak ditemukan.")
    ctx.session.organization_id = organization_id
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=ctx.user_id,
        action="auth.switch_organization",
        entity_type="organization",
        entity_id=organization_id,
        ip_address=ctx.ip_address,
    )
    db.commit()
    return membership


# --------------------------------------------------------------------------- organization


def update_organization(
    db: Session, ctx: RequestContext, payload: OrganizationUpdate
) -> Organization:
    org = ctx.organization
    before = audit.snapshot(org, ORG_FIELDS)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and value is None:
            raise BusinessValidationError("Nama organisasi wajib diisi.")
        setattr(org, field, value)
    changes = audit.diff(before, audit.snapshot(org, ORG_FIELDS))
    if changes:
        audit.record(
            db,
            organization_id=org.id,
            actor_user_id=ctx.user_id,
            action="organization.update",
            entity_type="organization",
            entity_id=org.id,
            summary=org.name,
            changes=changes,
            ip_address=ctx.ip_address,
        )
    db.commit()
    db.refresh(org)
    return org


# --------------------------------------------------------------------------- members


def list_members(db: Session, ctx: RequestContext) -> list[Membership]:
    return list(
        db.execute(
            select(Membership)
            .join(User, Membership.user_id == User.id)
            .where(Membership.organization_id == ctx.organization_id)
            .order_by(User.full_name)
        ).scalars()
    )


def get_member(db: Session, ctx: RequestContext, user_id: uuid.UUID) -> Membership:
    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == ctx.organization_id, Membership.user_id == user_id
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Pengguna tidak ditemukan.")
    return membership


def add_member(db: Session, ctx: RequestContext, payload: MemberCreate) -> Membership:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None:
        if payload.password is None:
            raise BusinessValidationError(
                "Kata sandi awal wajib diisi untuk pengguna baru.",
                details=[{"loc": ["body", "password"]}],
            )
        user = User(
            email=payload.email,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
        )
        db.add(user)
        db.flush()
    else:
        existing = db.execute(
            select(Membership).where(
                Membership.organization_id == ctx.organization_id,
                Membership.user_id == user.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("Pengguna sudah menjadi anggota organisasi ini.")

    membership = Membership(organization_id=ctx.organization_id, user_id=user.id, role=payload.role)
    db.add(membership)
    db.flush()
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="member.add",
        entity_type="user",
        entity_id=user.id,
        summary=user.email,
        changes={"role": {"from": None, "to": payload.role}},
        ip_address=ctx.ip_address,
    )
    db.commit()
    db.refresh(membership)
    return membership


def _active_owner_count(db: Session, organization_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count())
        .select_from(Membership)
        .join(User, Membership.user_id == User.id)
        .where(
            Membership.organization_id == organization_id,
            Membership.role == Role.OWNER,
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
    ).scalar_one()


def update_member(
    db: Session, ctx: RequestContext, user_id: uuid.UUID, payload: MemberUpdate
) -> Membership:
    # Lock the organization's owner rows so two admins cannot demote each other concurrently.
    db.execute(
        select(Membership.id)
        .where(Membership.organization_id == ctx.organization_id, Membership.role == Role.OWNER)
        .with_for_update()
    )
    membership = get_member(db, ctx, user_id)
    before = {"role": membership.role.value, "is_active": membership.is_active}

    loses_owner = (
        membership.role == Role.OWNER
        and membership.is_active
        and (
            (payload.role is not None and payload.role != Role.OWNER) or payload.is_active is False
        )
    )
    if loses_owner and _active_owner_count(db, ctx.organization_id) <= 1:
        raise ConflictError("Organisasi harus memiliki minimal satu Owner/Admin aktif.")
    if user_id == ctx.user_id and payload.is_active is False:
        raise PermissionDeniedError("Anda tidak dapat menonaktifkan akun Anda sendiri.")

    if payload.role is not None:
        membership.role = payload.role
    if payload.is_active is not None:
        membership.is_active = payload.is_active

    after = {"role": membership.role.value, "is_active": membership.is_active}
    changes = audit.diff(before, after)
    if changes:
        if membership.is_active is False or "role" in changes:
            # Force re-login so the new role/permissions apply immediately.
            revoke_user_sessions(db, user_id, organization_id=ctx.organization_id)
        audit.record(
            db,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action="member.update",
            entity_type="user",
            entity_id=user_id,
            summary=membership.user.email,
            changes=changes,
            ip_address=ctx.ip_address,
        )
    db.commit()
    db.refresh(membership)
    return membership


def require_member_user(db: Session, ctx: RequestContext, user_id: uuid.UUID) -> User:
    """Ensures the user belongs (actively) to the caller's organization."""
    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == ctx.organization_id,
            Membership.user_id == user_id,
            Membership.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if membership is None:
        raise BusinessValidationError(
            "Pengguna bukan anggota aktif organisasi ini.", details={"user_id": str(user_id)}
        )
    return membership.user
