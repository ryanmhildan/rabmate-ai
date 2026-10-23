from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    RequestContext,
    client_ip,
    get_context,
    require,
)
from app.core.config import Settings, get_settings
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.modules.identity import service
from app.modules.identity.models import Membership
from app.modules.identity.permissions import ROLE_LABELS, ROLE_PERMISSIONS, Permission, Role
from app.modules.identity.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MemberCreate,
    MemberOut,
    MemberUpdate,
    MeResponse,
    OrganizationBrief,
    OrganizationChoice,
    OrganizationOut,
    OrganizationUpdate,
    RoleOut,
    SwitchOrganizationRequest,
    UserBrief,
)
from app.modules.identity.sessions import IssuedSession

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

auth_router = APIRouter(prefix="/auth", tags=["auth"], responses=ERRORS)
org_router = APIRouter(prefix="/organizations", tags=["organizations"], responses=ERRORS)
users_router = APIRouter(prefix="/users", tags=["users"], responses=ERRORS)
roles_router = APIRouter(prefix="/roles", tags=["users"], responses=ERRORS)


def _set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    max_age = settings.session_max_age_hours * 3600
    secure = settings.cookies_secure
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    # Readable by the page's JS so it can echo it in X-CSRF-Token (double submit, bound to the
    # server-side session hash).
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=settings.cookies_secure, samesite="lax")


def _me(db: Session, membership: Membership) -> MeResponse:
    memberships = service.active_memberships(db, membership.user_id)
    return MeResponse(
        user=UserBrief.model_validate(membership.user),
        organization=OrganizationBrief.model_validate(membership.organization),
        role=membership.role,
        role_label=ROLE_LABELS[membership.role],
        permissions=sorted(ROLE_PERMISSIONS[membership.role]),
        organizations=[
            OrganizationChoice(id=m.organization.id, name=m.organization.name, role=m.role)
            for m in memberships
        ],
    )


def _member_out(membership: Membership) -> MemberOut:
    return MemberOut(
        id=membership.user.id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,
        role_label=ROLE_LABELS[membership.role],
        is_active=membership.is_active and membership.user.is_active,
        last_login_at=membership.user.last_login_at,
        joined_at=membership.created_at,
    )


# --------------------------------------------------------------------------- auth


@auth_router.post(
    "/login",
    response_model=MeResponse,
    summary="Masuk; menyetel cookie sesi (HttpOnly) dan cookie CSRF",
    responses={429: {"model": ErrorResponse}},
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    result = service.login(
        db,
        payload,
        settings=settings,
        ip=client_ip(request, settings),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(response, result.issued, settings)
    return _me(db, result.membership)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Keluar")
def logout(
    ctx: RequestContext = Depends(get_context),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    service.logout(db, ctx)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookies(response, settings)
    return response


@auth_router.get("/me", response_model=MeResponse, summary="Pengguna & organisasi aktif")
def me(ctx: RequestContext = Depends(get_context), db: Session = Depends(get_db)) -> MeResponse:
    return _me(db, ctx.membership)


@auth_router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Ganti kata sandi (sesi lain dicabut)",
)
def change_password(
    payload: ChangePasswordRequest,
    ctx: RequestContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> Response:
    service.change_password(db, ctx, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post(
    "/switch-organization", response_model=MeResponse, summary="Ganti organisasi aktif"
)
def switch_organization(
    payload: SwitchOrganizationRequest,
    ctx: RequestContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> MeResponse:
    return _me(db, service.switch_organization(db, ctx, payload.organization_id))


# --------------------------------------------------------------------------- organization


@org_router.get("/current", response_model=OrganizationOut, summary="Profil perusahaan")
def get_organization(
    ctx: RequestContext = Depends(require(Permission.ORG_READ)),
) -> OrganizationOut:
    return OrganizationOut.model_validate(ctx.organization)


@org_router.patch("/current", response_model=OrganizationOut, summary="Ubah profil perusahaan")
def update_organization(
    payload: OrganizationUpdate,
    ctx: RequestContext = Depends(require(Permission.ORG_UPDATE)),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    return OrganizationOut.model_validate(service.update_organization(db, ctx, payload))


# --------------------------------------------------------------------------- users & roles


@roles_router.get("", response_model=list[RoleOut], summary="Daftar role dan izinnya")
def list_roles(_: RequestContext = Depends(get_context)) -> list[RoleOut]:
    return [
        RoleOut(role=role, label=ROLE_LABELS[role], permissions=sorted(ROLE_PERMISSIONS[role]))
        for role in Role
    ]


@users_router.get("", response_model=list[MemberOut], summary="Anggota organisasi")
def list_users(
    ctx: RequestContext = Depends(require(Permission.USERS_READ)),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    return [_member_out(m) for m in service.list_members(db, ctx)]


@users_router.post(
    "",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tambah pengguna ke organisasi",
)
def add_user(
    payload: MemberCreate,
    ctx: RequestContext = Depends(require(Permission.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> MemberOut:
    return _member_out(service.add_member(db, ctx, payload))


@users_router.patch("/{user_id}", response_model=MemberOut, summary="Ubah role/status pengguna")
def update_user(
    user_id: uuid.UUID,
    payload: MemberUpdate,
    ctx: RequestContext = Depends(require(Permission.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> MemberOut:
    return _member_out(service.update_member(db, ctx, user_id, payload))
