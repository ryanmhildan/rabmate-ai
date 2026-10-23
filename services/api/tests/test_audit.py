from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.audit.service import diff
from tests.factories import Tenant


def _logs(db: Session, tenant: Tenant, action: str) -> list[AuditLog]:
    return list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == tenant.org.id, AuditLog.action == action)
            .order_by(AuditLog.created_at)
        ).scalars()
    )


def test_diff_reports_only_changed_fields_and_never_secrets() -> None:
    before = {"name": "A", "city": "X", "password_hash": "old"}
    after = {"name": "B", "city": "X", "password_hash": "new"}
    assert diff(before, after) == {"name": {"from": "A", "to": "B"}}


def test_client_lifecycle_is_audited_with_actor_and_diff(
    db_session: Session, tenant: Tenant
) -> None:
    client = tenant.browser.post("/api/v1/clients", json={"name": "Audit", "city": "Bogor"}).json()
    tenant.browser.patch(
        f"/api/v1/clients/{client['id']}", json={"version": 1, "city": "Depok", "notes": None}
    )
    tenant.browser.delete(f"/api/v1/clients/{client['id']}")

    created = _logs(db_session, tenant, "client.create")[0]
    updated = _logs(db_session, tenant, "client.update")[0]
    deleted = _logs(db_session, tenant, "client.delete")[0]

    assert created.actor_user_id == tenant.owner.id
    assert created.changes is not None and created.changes["name"] == {"from": None, "to": "Audit"}
    assert updated.changes == {"city": {"from": "Bogor", "to": "Depok"}}
    assert deleted.summary == "Audit"
    assert created.request_id is not None


def test_noop_update_writes_no_audit_entry(db_session: Session, tenant: Tenant) -> None:
    client = tenant.browser.post("/api/v1/clients", json={"name": "Sama"}).json()
    response = tenant.browser.patch(
        f"/api/v1/clients/{client['id']}", json={"version": 1, "name": "Sama"}
    )
    assert response.json()["version"] == 1
    assert _logs(db_session, tenant, "client.update") == []


def test_project_money_is_audited_as_exact_strings(db_session: Session, tenant: Tenant) -> None:
    project = tenant.browser.post(
        "/api/v1/projects",
        json={"name": "Audit uang", "project_type": "it", "budget_amount": "100.10"},
    ).json()
    tenant.browser.patch(
        f"/api/v1/projects/{project['id']}", json={"version": 1, "budget_amount": "200.20"}
    )

    change = _logs(db_session, tenant, "project.update")[0].changes
    assert change == {"budget_amount": {"from": "100.10", "to": "200.20"}}


def test_status_changes_get_their_own_action(db_session: Session, tenant: Tenant) -> None:
    project = tenant.browser.post(
        "/api/v1/projects", json={"name": "Status", "project_type": "it"}
    ).json()
    tenant.browser.patch(
        f"/api/v1/projects/{project['id']}", json={"version": 1, "status": "active"}
    )

    entry = _logs(db_session, tenant, "project.status_change")[0]
    assert entry.changes == {"status": {"from": "prospect", "to": "active"}}


def test_role_changes_are_audited(db_session: Session, tenant: Tenant) -> None:
    member = tenant.browser.post(
        "/api/v1/users",
        json={"email": "r@contoh.co.id", "full_name": "R", "role": "viewer", "password": "x" * 12},
    ).json()
    tenant.browser.patch(f"/api/v1/users/{member['id']}", json={"role": "finance"})

    entry = _logs(db_session, tenant, "member.update")[0]
    assert entry.changes == {"role": {"from": "viewer", "to": "finance"}}
    assert "x" * 12 not in str(_logs(db_session, tenant, "member.add")[0].changes)


def test_audit_endpoint_filters_and_includes_actor(tenant: Tenant) -> None:
    client = tenant.browser.post("/api/v1/clients", json={"name": "Filter"}).json()

    page = tenant.browser.get(
        "/api/v1/audit-logs", params={"entity_type": "client", "entity_id": client["id"]}
    ).json()

    assert page["total"] == 1
    item = page["items"][0]
    assert item["action"] == "client.create"
    assert item["actor"]["email"] == tenant.owner.email


def test_dashboard_summary_counts(tenant: Tenant) -> None:
    b = tenant.browser
    b.post("/api/v1/clients", json={"name": "Aktif"})
    b.post("/api/v1/projects", json={"name": "A", "project_type": "it", "budget_amount": "100.50"})
    b.post("/api/v1/projects", json={"name": "B", "project_type": "it", "budget_amount": "200"})
    b.post(
        "/api/v1/projects",
        json={"name": "C", "project_type": "it", "currency": "USD", "budget_amount": "10"},
    )

    summary = b.get("/api/v1/dashboard/summary").json()

    assert summary["projects_total"] == 3
    assert summary["projects_by_status"]["prospect"] == 3
    assert summary["clients_active"] == 1
    assert summary["open_budget"] == [
        {"currency": "IDR", "total": "300.50", "projects": 2},
        {"currency": "USD", "total": "10.00", "projects": 1},
    ]
    assert summary["recent_activity"][0]["action"] == "project.create"
