from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.modules.audit.models import AuditLog
from app.modules.identity.models import LoginAttempt, UserSession
from app.modules.identity.permissions import Role
from app.modules.identity.sessions import utcnow
from tests.factories import DEFAULT_PASSWORD, Tenant, login, make_org, make_user

ME = "/api/v1/auth/me"


def _session_row(db: Session, browser: TestClient) -> UserSession:
    token = browser.cookies["rabmate_session"]
    return db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).scalar_one()


# --------------------------------------------------------------------------- login


def test_login_sets_httponly_session_and_readable_csrf_cookie(
    db_session: Session, app_client: TestClient
) -> None:
    org = make_org(db_session, "PT Login")
    user = make_user(db_session, org, Role.ESTIMATOR, email="budi@contoh.co.id")

    response = app_client.post(
        "/api/v1/auth/login", json={"email": "  BUDI@Contoh.co.id ", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == "budi@contoh.co.id"
    assert body["organization"]["name"] == "PT Login"
    assert body["role"] == "estimator"
    assert "rab.write" in body["permissions"]
    assert "users.manage" not in body["permissions"]

    set_cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookies if c.startswith("rabmate_session="))
    csrf_cookie = next(c for c in set_cookies if c.startswith("rabmate_csrf="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    # Only hashes are stored server-side.
    stored = db_session.execute(
        select(UserSession).where(UserSession.user_id == user.id)
    ).scalar_one()
    assert stored.token_hash != app_client.cookies["rabmate_session"]
    assert stored.token_hash == hash_token(app_client.cookies["rabmate_session"])


def test_wrong_password_and_unknown_email_look_identical(
    db_session: Session, app_client: TestClient
) -> None:
    make_user(db_session, make_org(db_session), email="ada@contoh.co.id")

    wrong = login(app_client, "ada@contoh.co.id", "salah-sandi-123")
    unknown = login(app_client, "tidakada@contoh.co.id", "salah-sandi-123")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "rabmate_session" not in app_client.cookies


def test_inactive_user_and_user_without_active_membership_cannot_log_in(
    db_session: Session, app_client: TestClient
) -> None:
    org = make_org(db_session)
    make_user(db_session, org, email="nonaktif@contoh.co.id", active=False)
    make_user(db_session, org, email="keluar@contoh.co.id", membership_active=False)
    make_user(db_session, None, email="tanpaorg@contoh.co.id")

    for email in ("nonaktif@contoh.co.id", "keluar@contoh.co.id", "tanpaorg@contoh.co.id"):
        assert login(app_client, email).status_code == 401, email


def test_login_is_throttled_after_repeated_failures(
    db_session: Session, app_client: TestClient
) -> None:
    make_user(db_session, make_org(db_session), email="target@contoh.co.id")

    for _ in range(5):
        assert login(app_client, "target@contoh.co.id", "tebakan-salah-1").status_code == 401

    blocked = login(app_client, "target@contoh.co.id")  # even the right password
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0

    attempts = db_session.execute(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.email == "target@contoh.co.id")
    ).scalar_one()
    assert attempts == 5, "throttled requests are not counted as attempts"


def test_old_failures_outside_window_do_not_throttle(
    db_session: Session, app_client: TestClient
) -> None:
    make_user(db_session, make_org(db_session), email="lama@contoh.co.id")
    long_ago = utcnow() - timedelta(hours=2)
    for _ in range(10):
        db_session.add(
            LoginAttempt(
                email="lama@contoh.co.id", ip_address="x", succeeded=False, created_at=long_ago
            )
        )
    db_session.flush()

    assert login(app_client, "lama@contoh.co.id").status_code == 200


def test_successful_login_is_audited_without_secrets(db_session: Session, tenant: Tenant) -> None:
    entry = db_session.execute(
        select(AuditLog).where(
            AuditLog.organization_id == tenant.org.id, AuditLog.action == "auth.login"
        )
    ).scalar_one()
    assert entry.actor_user_id == tenant.owner.id
    assert entry.changes is None
    assert DEFAULT_PASSWORD not in (entry.summary or "")


# --------------------------------------------------------------------------- session


def test_me_requires_a_session(app_client: TestClient) -> None:
    response = app_client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_forged_session_cookie_is_rejected(app_client: TestClient) -> None:
    app_client.cookies.set("rabmate_session", "bukan-token-asli")
    assert app_client.get(ME).status_code == 401


def test_logout_revokes_the_session(db_session: Session, tenant: Tenant) -> None:
    browser = tenant.browser
    token = browser.cookies["rabmate_session"]

    response = browser.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert browser.get(ME).status_code == 401
    # Replaying the old cookie does not work either.
    replay = tenant.browser
    replay.cookies.set("rabmate_session", token)
    assert replay.get(ME).status_code == 401


def test_expired_and_idle_sessions_are_rejected(db_session: Session, tenant: Tenant) -> None:
    session = _session_row(db_session, tenant.browser)

    session.last_seen_at = utcnow() - timedelta(hours=9)  # idle timeout is 8h
    db_session.flush()
    assert tenant.browser.get(ME).status_code == 401

    session.last_seen_at = utcnow()
    session.expires_at = utcnow() - timedelta(seconds=1)
    db_session.flush()
    assert tenant.browser.get(ME).status_code == 401


def test_deactivated_membership_ends_existing_session(
    db_session: Session, tenant: Tenant, login_as: Callable[..., TestClient]
) -> None:
    member = make_user(db_session, tenant.org, Role.VIEWER)
    browser = login_as(member)
    assert browser.get(ME).status_code == 200

    response = tenant.browser.patch(f"/api/v1/users/{member.id}", json={"is_active": False})

    assert response.status_code == 200, response.text
    assert browser.get(ME).status_code == 401


# --------------------------------------------------------------------------- CSRF / origin


def test_mutations_require_csrf_header(tenant: Tenant) -> None:
    browser = tenant.browser
    token = browser.headers.pop("X-CSRF-Token")

    missing = browser.post("/api/v1/clients", json={"name": "Tanpa CSRF"})
    browser.headers["X-CSRF-Token"] = "token-palsu"
    forged = browser.post("/api/v1/clients", json={"name": "CSRF palsu"})
    browser.headers["X-CSRF-Token"] = token
    ok = browser.post("/api/v1/clients", json={"name": "Dengan CSRF"})

    assert missing.status_code == forged.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"
    assert ok.status_code == 201


def test_csrf_token_is_bound_to_its_session(
    db_session: Session, tenant: Tenant, login_as: Callable[..., TestClient]
) -> None:
    other = login_as(make_user(db_session, tenant.org, Role.OWNER))
    tenant.browser.headers["X-CSRF-Token"] = other.headers["X-CSRF-Token"]

    response = tenant.browser.post("/api/v1/clients", json={"name": "Token orang lain"})

    assert response.status_code == 403


def test_safe_methods_do_not_need_csrf(tenant: Tenant) -> None:
    tenant.browser.headers.pop("X-CSRF-Token")
    assert tenant.browser.get(ME).status_code == 200


def test_cross_origin_mutation_is_rejected(tenant: Tenant) -> None:
    response = tenant.browser.post(
        "/api/v1/clients",
        json={"name": "Dari situs lain"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_rejected"


def test_allowed_origin_is_accepted(tenant: Tenant) -> None:
    response = tenant.browser.post(
        "/api/v1/clients",
        json={"name": "Dari web app"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 201


# --------------------------------------------------------------------------- password & orgs


def test_change_password_revokes_other_sessions(
    db_session: Session, tenant: Tenant, login_as: Callable[..., TestClient]
) -> None:
    second_browser = login_as(tenant.owner)

    response = tenant.browser.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "sandi-baru-yang-kuat"},
    )

    assert response.status_code == 204, response.text
    assert tenant.browser.get(ME).status_code == 200
    assert second_browser.get(ME).status_code == 401
    assert login(second_browser, tenant.owner.email, "sandi-baru-yang-kuat").status_code == 200


def test_change_password_checks_current_and_policy(tenant: Tenant) -> None:
    wrong = tenant.browser.post(
        "/api/v1/auth/change-password",
        json={"current_password": "bukan-ini-123", "new_password": "sandi-baru-yang-kuat"},
    )
    short = tenant.browser.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "pendek"},
    )
    assert wrong.status_code == 422
    assert short.status_code == 422


def test_switch_organization_changes_scope(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    # The tenant owner is also a viewer in the other organization.
    from app.modules.identity.models import Membership

    db_session.add(
        Membership(organization_id=other_tenant.org.id, user_id=tenant.owner.id, role=Role.VIEWER)
    )
    db_session.flush()
    me = tenant.browser.get(ME).json()
    assert {o["name"] for o in me["organizations"]} == {"PT Alfa Konstruksi", "CV Beta Teknik"}

    switched = tenant.browser.post(
        "/api/v1/auth/switch-organization", json={"organization_id": str(other_tenant.org.id)}
    )

    assert switched.status_code == 200, switched.text
    assert switched.json()["organization"]["name"] == "CV Beta Teknik"
    assert switched.json()["role"] == "viewer"
    assert tenant.browser.post("/api/v1/clients", json={"name": "x"}).status_code == 403


def test_cannot_switch_to_foreign_organization(tenant: Tenant, other_tenant: Tenant) -> None:
    response = tenant.browser.post(
        "/api/v1/auth/switch-organization", json={"organization_id": str(other_tenant.org.id)}
    )
    assert response.status_code == 404
