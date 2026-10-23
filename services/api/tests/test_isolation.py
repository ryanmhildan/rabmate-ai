"""Tenant isolation: every path — list, detail, update, delete, references — is org-scoped.

Objects of another organization must be indistinguishable from objects that do not exist (404).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from tests.factories import Tenant, make_client, make_project


def test_lists_only_show_own_organization(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    make_client(db_session, tenant.org, name="Klien Alfa")
    make_client(db_session, other_tenant.org, name="Klien Beta")
    make_project(db_session, tenant.org, name="Proyek Alfa")
    make_project(db_session, other_tenant.org, name="Proyek Beta")

    clients = tenant.browser.get("/api/v1/clients").json()
    projects = tenant.browser.get("/api/v1/projects").json()
    users = tenant.browser.get("/api/v1/users").json()

    assert [c["name"] for c in clients["items"]] == ["Klien Alfa"]
    assert [p["name"] for p in projects["items"]] == ["Proyek Alfa"]
    assert [u["email"] for u in users] == [tenant.owner.email]


def test_foreign_client_is_not_found_on_every_path(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    foreign = make_client(db_session, other_tenant.org, name="Rahasia Beta")
    url = f"/api/v1/clients/{foreign.id}"
    b = tenant.browser

    responses = [
        b.get(url),
        b.patch(url, json={"version": 1, "name": "Dibajak"}),
        b.delete(url),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert all("Rahasia" not in r.text for r in responses)
    db_session.refresh(foreign)
    assert foreign.name == "Rahasia Beta"


def test_foreign_project_is_not_found_on_every_path(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    foreign = make_project(db_session, other_tenant.org, name="Proyek Beta")
    url = f"/api/v1/projects/{foreign.id}"
    b = tenant.browser

    responses = [
        b.get(url),
        b.patch(url, json={"version": 1, "name": "Dibajak"}),
        b.put(f"{url}/members", json={"members": []}),
        b.delete(url),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404]
    db_session.refresh(foreign)
    assert foreign.name == "Proyek Beta"


def test_unknown_id_and_foreign_id_return_the_same_error(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    foreign = make_client(db_session, other_tenant.org)

    a = tenant.browser.get(f"/api/v1/clients/{foreign.id}").json()["error"]
    b = tenant.browser.get(f"/api/v1/clients/{uuid.uuid4()}").json()["error"]

    assert (a["code"], a["message"]) == (b["code"], b["message"])


def test_project_cannot_reference_foreign_client_or_user(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    foreign_client = make_client(db_session, other_tenant.org)

    with_client = tenant.browser.post(
        "/api/v1/projects",
        json={"name": "P", "project_type": "it", "client_id": str(foreign_client.id)},
    )
    with_owner = tenant.browser.post(
        "/api/v1/projects",
        json={"name": "P", "project_type": "it", "owner_id": str(other_tenant.owner.id)},
    )
    project = make_project(db_session, tenant.org)
    with_member = tenant.browser.put(
        f"/api/v1/projects/{project.id}/members",
        json={"members": [{"user_id": str(other_tenant.owner.id)}]},
    )

    assert with_client.status_code == with_owner.status_code == with_member.status_code == 422


def test_users_of_other_organization_cannot_be_managed(
    tenant: Tenant, other_tenant: Tenant
) -> None:
    response = tenant.browser.patch(
        f"/api/v1/users/{other_tenant.owner.id}", json={"role": "viewer"}
    )
    assert response.status_code == 404


def test_audit_log_and_dashboard_are_scoped(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    other_tenant.browser.post("/api/v1/clients", json={"name": "Aktivitas Beta"})
    make_project(db_session, other_tenant.org)

    logs = tenant.browser.get("/api/v1/audit-logs").json()
    summary = tenant.browser.get("/api/v1/dashboard/summary").json()

    assert all(item["summary"] != "Aktivitas Beta" for item in logs["items"])
    assert summary["projects_total"] == 0
    assert summary["clients_active"] == 0


def test_organization_profile_is_the_callers_own(tenant: Tenant, other_tenant: Tenant) -> None:
    assert (
        tenant.browser.get("/api/v1/organizations/current").json()["name"] == "PT Alfa Konstruksi"
    )
    tenant.browser.patch("/api/v1/organizations/current", json={"city": "Bandung"})
    assert other_tenant.browser.get("/api/v1/organizations/current").json()["city"] is None
