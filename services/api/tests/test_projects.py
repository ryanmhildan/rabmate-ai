from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.modules.identity.permissions import Role
from app.modules.projects.lifecycle import STATUS_TRANSITIONS, can_transition
from app.modules.projects.models import ProjectStatus
from tests.factories import Tenant, make_client, make_project, make_user

URL = "/api/v1/projects"
YEAR = datetime.now(ZoneInfo("Asia/Jakarta")).year


def _create(tenant: Tenant, **body: object) -> dict[str, Any]:
    response = tenant.browser.post(URL, json={"name": "Proyek", "project_type": "other", **body})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_numbers_are_sequential_per_organization(tenant: Tenant, other_tenant: Tenant) -> None:
    first = _create(tenant)
    second = _create(tenant)
    other = _create(other_tenant)
    manual = _create(tenant, number="KONTRAK/2026/7")

    assert first["number"] == f"PRJ-{YEAR}-0001"
    assert second["number"] == f"PRJ-{YEAR}-0002"
    assert other["number"] == f"PRJ-{YEAR}-0001"
    assert manual["number"] == "KONTRAK/2026/7"
    duplicate = tenant.browser.post(
        URL, json={"name": "Dup", "project_type": "it", "number": "KONTRAK/2026/7"}
    )
    assert duplicate.status_code == 409


def test_full_project_for_any_industry(db_session: Session, tenant: Tenant) -> None:
    client = make_client(db_session, tenant.org, name="Dinas PU")
    pm = make_user(db_session, tenant.org, Role.PROJECT_MANAGER)

    project = _create(
        tenant,
        name="Renovasi Gedung Arsip",
        project_type="construction",
        client_id=str(client.id),
        location="Bandung",
        start_date="2026-11-01",
        end_date="2027-03-31",
        tax_label="PPN",
        tax_rate_percent="11",
        budget_amount="1250000000.50",
        owner_id=str(pm.id),
        attributes={"luas_bangunan_m2": 850, "jumlah_lantai": 3, "izin_pbg": True},
    )

    assert project["client"]["name"] == "Dinas PU"
    assert project["owner"]["id"] == str(pm.id)
    # Money and rates round-trip as exact decimal strings.
    assert project["budget_amount"] == "1250000000.50"
    assert project["tax_rate_percent"] == "11.00"
    assert project["currency"] == "IDR"
    assert project["status"] == "prospect"
    assert project["allowed_status_transitions"] == ["active", "cancelled"]
    assert project["attributes"]["luas_bangunan_m2"] == 850

    # An IT project needs none of the construction attributes.
    it = _create(tenant, name="Aplikasi Gudang", project_type="it")
    assert it["attributes"] == {} and it["location"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"start_date": "2026-05-01", "end_date": "2026-04-30"},
        {"tax_label": "PPN"},
        {"tax_rate_percent": "11"},
        {"tax_label": "PPN", "tax_rate_percent": "101"},
        {"budget_amount": "-1"},
        {"budget_amount": "1.005"},
        {"budget_amount": 1.5},
        {"tax_label": "PPN", "tax_rate_percent": 11.5},
        {"currency": "idr"},
        {"attributes": {"Bad Key": 1}},
        {"attributes": {"catatan": "x" * 501}},
        {"attributes": {"nested": {"a": 1}}},
        {"attributes": {f"a{i}": i for i in range(31)}},
        {"project_type": "spaceship"},
    ],
)
def test_validation(tenant: Tenant, body: dict[str, object]) -> None:
    response = tenant.browser.post(URL, json={"name": "Validasi", "project_type": "it", **body})
    assert response.status_code == 422, (body, response.text)


def test_money_must_be_sent_as_string_to_keep_precision(tenant: Tenant) -> None:
    # As a JSON number this value would arrive as a float and lose its cents.
    as_number = tenant.browser.post(
        URL, json={"name": "Float", "project_type": "it", "budget_amount": 12345678901234567.89}
    )
    as_string = tenant.browser.post(
        URL, json={"name": "Str", "project_type": "it", "budget_amount": "12345678901234567.89"}
    )
    as_integer = tenant.browser.post(
        URL, json={"name": "Int", "project_type": "it", "budget_amount": 5000000}
    )

    assert as_number.status_code == 422
    assert "string" in as_number.text
    assert as_string.json()["budget_amount"] == "12345678901234567.89"
    assert as_integer.json()["budget_amount"] == "5000000.00"


def test_patch_rules_apply_to_merged_state(tenant: Tenant) -> None:
    project = _create(tenant, start_date="2026-01-10", tax_label="PPN", tax_rate_percent="11")
    url = f"{URL}/{project['id']}"

    end_before_start = tenant.browser.patch(url, json={"version": 1, "end_date": "2026-01-01"})
    drop_rate_only = tenant.browser.patch(url, json={"version": 1, "tax_rate_percent": None})
    drop_both = tenant.browser.patch(
        url, json={"version": 1, "tax_label": None, "tax_rate_percent": None}
    )

    assert end_before_start.status_code == 422
    assert drop_rate_only.status_code == 422
    assert drop_both.status_code == 200, drop_both.text
    assert drop_both.json()["tax_label"] is None


def test_status_transitions_follow_lifecycle(tenant: Tenant) -> None:
    project = _create(tenant)
    url = f"{URL}/{project['id']}"
    version = 1

    def move(status: str) -> int:
        nonlocal version
        response = tenant.browser.patch(url, json={"version": version, "status": status})
        if response.status_code == 200:
            version = response.json()["version"]
        return response.status_code

    assert move("completed") == 422  # prospect cannot jump to completed
    assert move("active") == 200
    assert move("on_hold") == 200
    assert move("completed") == 422  # must resume first
    assert move("active") == 200
    assert move("completed") == 200
    assert move("prospect") == 422
    assert move("active") == 200  # reopen


def test_transition_table_is_consistent() -> None:
    assert set(STATUS_TRANSITIONS) == set(ProjectStatus)
    for status in ProjectStatus:
        assert can_transition(status, status)
        assert status not in STATUS_TRANSITIONS[status]


def test_members_replace_and_update_in_place(db_session: Session, tenant: Tenant) -> None:
    a = make_user(db_session, tenant.org, Role.ESTIMATOR)
    b = make_user(db_session, tenant.org, Role.VIEWER)
    inactive = make_user(db_session, tenant.org, Role.VIEWER, membership_active=False)
    project = _create(tenant)
    url = f"{URL}/{project['id']}/members"

    first = tenant.browser.put(
        url, json={"members": [{"user_id": str(a.id), "role": "lead"}, {"user_id": str(b.id)}]}
    )
    assert first.status_code == 200, first.text
    assert {(m["user"]["id"], m["role"]) for m in first.json()["members"]} == {
        (str(a.id), "lead"),
        (str(b.id), "member"),
    }

    second = tenant.browser.put(url, json={"members": [{"user_id": str(a.id), "role": "member"}]})
    assert second.status_code == 200, second.text
    assert [(m["user"]["id"], m["role"]) for m in second.json()["members"]] == [
        (str(a.id), "member")
    ]

    assert (
        tenant.browser.put(url, json={"members": [{"user_id": str(inactive.id)}]}).status_code
        == 422
    )
    dup = {"members": [{"user_id": str(a.id)}, {"user_id": str(a.id)}]}
    assert tenant.browser.put(url, json=dup).status_code == 422


def test_filters_and_search(db_session: Session, tenant: Tenant) -> None:
    client = make_client(db_session, tenant.org, name="PT Pelanggan Setia")
    make_project(db_session, tenant.org, name="Pagar Pabrik", status=ProjectStatus.ACTIVE)
    make_project(db_session, tenant.org, name="Server Kantor", client_id=client.id)
    b = tenant.browser

    assert b.get(URL, params={"status": "active"}).json()["total"] == 1
    assert [p["name"] for p in b.get(URL, params={"q": "setia"}).json()["items"]] == [
        "Server Kantor"
    ]
    assert b.get(URL, params={"client_id": str(client.id)}).json()["total"] == 1
    assert b.get(URL, params={"status": "unknown"}).status_code == 422


def test_delete(tenant: Tenant) -> None:
    project = _create(tenant)
    assert tenant.browser.delete(f"{URL}/{project['id']}").status_code == 204
    assert tenant.browser.get(f"{URL}/{project['id']}").status_code == 404
