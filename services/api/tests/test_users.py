from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.identity.permissions import Role
from tests.factories import LoginAs, Tenant, login, make_org, make_user


def test_organization_profile_update(tenant: Tenant) -> None:
    response = tenant.browser.patch(
        "/api/v1/organizations/current",
        json={"legal_name": "PT Alfa Konstruksi Tbk", "tax_id": "0123456789012345", "city": ""},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["legal_name"] == "PT Alfa Konstruksi Tbk"
    assert body["tax_id"] == "0123456789012345"
    assert body["city"] is None
    assert (
        tenant.browser.patch("/api/v1/organizations/current", json={"name": None}).status_code
        == 422
    )


def test_roles_endpoint_lists_matrix(tenant: Tenant) -> None:
    roles = {r["role"]: r for r in tenant.browser.get("/api/v1/roles").json()}
    assert set(roles) == {r.value for r in Role}
    assert roles["owner"]["label"] == "Owner/Admin"
    assert "users.manage" not in roles["viewer"]["permissions"]


def test_add_new_user_and_log_in(tenant: Tenant, client_factory: Callable[[], TestClient]) -> None:
    response = tenant.browser.post(
        "/api/v1/users",
        json={
            "email": "Siti@Contoh.co.id",
            "full_name": "Siti Rahma",
            "role": "estimator",
            "password": "sandi-awal-siti-1",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["email"] == "siti@contoh.co.id"
    assert response.json()["role_label"] == "Estimator"
    assert login(client_factory(), "siti@contoh.co.id", "sandi-awal-siti-1").status_code == 200


def test_new_user_requires_password_and_policy(tenant: Tenant) -> None:
    base = {"email": "baru@contoh.co.id", "full_name": "Baru", "role": "viewer"}
    assert tenant.browser.post("/api/v1/users", json=base).status_code == 422
    assert (
        tenant.browser.post("/api/v1/users", json={**base, "password": "pendek"}).status_code == 422
    )


def test_existing_user_from_other_org_is_attached_without_touching_password(
    db_session: Session,
    tenant: Tenant,
    client_factory: Callable[[], TestClient],
) -> None:
    other_org = make_org(db_session)
    shared = make_user(db_session, other_org, Role.OWNER, email="konsultan@contoh.co.id")

    response = tenant.browser.post(
        "/api/v1/users",
        json={
            "email": "konsultan@contoh.co.id",
            "full_name": "Diabaikan",
            "role": "viewer",
            "password": "mencoba-mengganti-1",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["full_name"] == shared.full_name
    # Their original password still works; the one supplied here was ignored.
    assert login(client_factory(), "konsultan@contoh.co.id").status_code == 200
    again = tenant.browser.post(
        "/api/v1/users",
        json={"email": "konsultan@contoh.co.id", "full_name": "X", "role": "viewer"},
    )
    assert again.status_code == 409


def test_last_owner_cannot_be_demoted_or_deactivated(
    db_session: Session, tenant: Tenant, login_as: LoginAs
) -> None:
    url = f"/api/v1/users/{tenant.owner.id}"
    demote = tenant.browser.patch(url, json={"role": "viewer"})
    assert demote.status_code == 409
    assert "minimal satu Owner" in demote.json()["error"]["message"]

    second_owner = make_user(db_session, tenant.org, Role.OWNER)
    second_browser = login_as(second_owner)
    deactivate = second_browser.patch(url, json={"is_active": False})
    assert deactivate.status_code == 200, deactivate.text
    # Now second_owner is the last active owner.
    assert (
        second_browser.patch(
            f"/api/v1/users/{second_owner.id}", json={"role": "viewer"}
        ).status_code
        == 409
    )


def test_cannot_deactivate_self(db_session: Session, tenant: Tenant) -> None:
    make_user(db_session, tenant.org, Role.OWNER)  # so the last-owner rule is not what blocks
    response = tenant.browser.patch(f"/api/v1/users/{tenant.owner.id}", json={"is_active": False})
    assert response.status_code == 403


def test_users_list_shows_roles_and_status(db_session: Session, tenant: Tenant) -> None:
    make_user(db_session, tenant.org, Role.FINANCE, membership_active=False)
    users = tenant.browser.get("/api/v1/users").json()
    finance = next(u for u in users if u["role"] == "finance")
    assert finance["is_active"] is False
    assert finance["role_label"] == "Finance"
    assert "password" not in str(users).lower()
