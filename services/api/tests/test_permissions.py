"""Authorization is enforced by the backend for every role, not just hidden in the UI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.identity.permissions import ROLE_PERMISSIONS, Permission, Role
from tests.factories import LoginAs, Tenant, make_client, make_project, make_user


def test_owner_has_every_permission() -> None:
    assert ROLE_PERMISSIONS[Role.OWNER] == frozenset(Permission)


def test_every_role_can_read_core_data_and_viewer_is_read_only() -> None:
    for role, permissions in ROLE_PERMISSIONS.items():
        assert {Permission.ORG_READ, Permission.PROJECTS_READ} <= permissions, role
    writes = {p for p in ROLE_PERMISSIONS[Role.VIEWER] if not p.value.endswith(".read")}
    assert writes == set()


def test_only_owner_manages_users_and_organization() -> None:
    for role, permissions in ROLE_PERMISSIONS.items():
        expected = role is Role.OWNER
        assert (Permission.USERS_MANAGE in permissions) is expected, role
        assert (Permission.ORG_UPDATE in permissions) is expected, role


def test_approval_rights_are_separate_from_authoring() -> None:
    assert Permission.RAB_APPROVE not in ROLE_PERMISSIONS[Role.ESTIMATOR]
    assert Permission.RAB_APPROVE not in ROLE_PERMISSIONS[Role.PROJECT_MANAGER]
    assert Permission.RAB_APPROVE in ROLE_PERMISSIONS[Role.APPROVER]
    approvers = {
        r for r, perms in ROLE_PERMISSIONS.items() if Permission.DOCUMENTS_APPROVE in perms
    }
    assert approvers == {Role.OWNER, Role.APPROVER}


def test_ai_assistant_only_for_roles_that_author_rab() -> None:
    users = {r for r, perms in ROLE_PERMISSIONS.items() if Permission.AI_USE in perms}
    assert users == {Role.OWNER, Role.PROJECT_MANAGER, Role.ESTIMATOR}
    for role in users:
        assert Permission.RAB_WRITE in ROLE_PERMISSIONS[role], role


# (role, method, path template, json, expected status)
CASES = [
    (Role.VIEWER, "post", "/api/v1/clients", {"name": "X"}, 403),
    (Role.VIEWER, "patch", "/api/v1/clients/{client}", {"version": 1, "name": "Y"}, 403),
    (Role.VIEWER, "delete", "/api/v1/clients/{client}", None, 403),
    (Role.VIEWER, "post", "/api/v1/projects", {"name": "P", "project_type": "it"}, 403),
    (Role.VIEWER, "get", "/api/v1/users", None, 403),
    (Role.VIEWER, "get", "/api/v1/audit-logs", None, 403),
    (Role.ESTIMATOR, "post", "/api/v1/clients", {"name": "X"}, 403),
    (Role.ESTIMATOR, "delete", "/api/v1/projects/{project}", None, 403),
    (Role.FINANCE, "post", "/api/v1/clients", {"name": "Klien Finance"}, 201),
    (Role.FINANCE, "post", "/api/v1/projects", {"name": "P", "project_type": "it"}, 403),
    (Role.PROJECT_MANAGER, "post", "/api/v1/projects", {"name": "P", "project_type": "it"}, 201),
    (Role.PROJECT_MANAGER, "delete", "/api/v1/clients/{client}", None, 403),
    (
        Role.PROJECT_MANAGER,
        "post",
        "/api/v1/users",
        {"email": "a@b.co", "full_name": "A", "role": "viewer", "password": "sandi-panjang-1"},
        403,
    ),
    (Role.PROJECT_MANAGER, "patch", "/api/v1/organizations/current", {"name": "Baru"}, 403),
    (Role.APPROVER, "get", "/api/v1/audit-logs", None, 200),
    (Role.APPROVER, "patch", "/api/v1/projects/{project}", {"version": 1, "name": "Z"}, 403),
]


@pytest.mark.parametrize(("role", "method", "path", "body", "expected"), CASES)
def test_endpoint_permissions(
    db_session: Session,
    tenant: Tenant,
    login_as: LoginAs,
    role: Role,
    method: str,
    path: str,
    body: dict[str, object] | None,
    expected: int,
) -> None:
    client = make_client(db_session, tenant.org)
    project = make_project(db_session, tenant.org)
    browser: TestClient = login_as(make_user(db_session, tenant.org, role))

    url = path.format(client=client.id, project=project.id)
    response = browser.request(method.upper(), url, json=body)

    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["error"]["code"] == "forbidden"


def test_role_change_applies_immediately(
    db_session: Session, tenant: Tenant, login_as: LoginAs
) -> None:
    estimator = make_user(db_session, tenant.org, Role.ESTIMATOR)
    tenant.browser.patch(f"/api/v1/users/{estimator.id}", json={"role": "project_manager"})

    # The old session is revoked; a fresh login carries the new permissions.
    browser = login_as(estimator)
    assert browser.get("/api/v1/auth/me").json()["role"] == "project_manager"
    assert browser.post("/api/v1/clients", json={"name": "Boleh"}).status_code == 201
