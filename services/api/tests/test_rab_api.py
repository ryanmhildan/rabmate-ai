"""RAB API: totals, editing rules, workflow, versions, permissions, isolation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.approvals.models import ApprovalRecord
from app.modules.audit.models import AuditLog
from app.modules.identity.permissions import Role
from app.modules.projects.models import ProjectStatus
from tests.factories import LoginAs, Tenant, make_project, make_user

YEAR = datetime.now(ZoneInfo("Asia/Jakarta")).year

Json = dict[str, Any]


def ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


class Rab:
    """Small client for one RAB, so tests read as workflows."""

    def __init__(self, browser: TestClient, rab: Json) -> None:
        self.browser = browser
        self.id = rab["id"]
        self.number = rab["number"]

    def url(self, version: int = 1, suffix: str = "") -> str:
        return f"/api/v1/rab/{self.id}/versions/{version}{suffix}"

    def version(self, version: int = 1, browser: TestClient | None = None) -> Any:
        return ok((browser or self.browser).get(self.url(version)))

    def add(self, version: int = 1, **item: Any) -> Any:
        body = {"name": "Item", "quantity": "1", "unit": "unit", "price_source": "Manual", **item}
        return self.browser.post(self.url(version, "/items"), json=body)

    def act(
        self, action: str, version: int = 1, browser: TestClient | None = None, **body: Any
    ) -> Any:
        return (browser or self.browser).post(
            self.url(version, f"/transitions/{action}"), json=body
        )


@pytest.fixture
def project(db_session: Session, tenant: Tenant) -> Any:
    return make_project(
        db_session, tenant.org, tax_label="PPN", tax_rate_percent=Decimal("11"), currency="IDR"
    )


@pytest.fixture
def rab(tenant: Tenant, project: Any) -> Rab:
    created = ok(
        tenant.browser.post(f"/api/v1/projects/{project.id}/rab", json={"title": "RAB Gudang"}),
        201,
    )
    return Rab(tenant.browser, created)


def priced_rab(rab: Rab) -> Rab:
    ok(rab.add(name="Semen", quantity="10", unit="sak", unit_price="65000"), 201)
    ok(rab.add(name="Tukang", item_type="labor", quantity="5", unit="OH", unit_price="150000"), 201)
    return rab


# --------------------------------------------------------------------------- creation & totals


def test_create_rab_starts_with_draft_v1_and_project_tax(tenant: Tenant, rab: Rab) -> None:
    assert rab.number == f"RAB-{YEAR}-0001"
    version = rab.version()
    assert version["status"] == "draft"
    assert (version["tax_label"], version["tax_rate_percent"]) == ("PPN", "11.00")
    assert version["currency"] == "IDR"
    assert version["editable"] is True
    assert version["allowed_actions"] == ["submit", "archive"]
    assert [i["code"] for i in version["issues"]] == ["empty"]


def test_items_drive_totals_with_tax_after_discount(rab: Rab) -> None:
    priced_rab(rab)
    version = rab.version()
    assert [i["subtotal"] for i in version["items"]] == ["650000.00", "750000.00"]
    assert version["totals"]["subtotal"] == "1400000.00"
    assert version["totals"]["tax_amount"] == "154000.00"
    assert version["totals"]["grand_total"] == "1554000.00"

    updated = ok(
        rab.browser.patch(
            rab.url(),
            json={
                "lock_version": version["lock_version"],
                "discount_type": "percent",
                "discount_value": "10",
            },
        )
    )
    totals = updated["totals"]
    assert totals["discount_amount"] == "140000.00"
    assert totals["taxable_base"] == "1260000.00"
    assert totals["tax_amount"] == "138600.00"
    assert totals["grand_total"] == "1398600.00"


def test_line_rounding_and_exact_strings(rab: Rab) -> None:
    item = ok(rab.add(quantity="3", unit_price="33.335"), 201)["items"][0]
    assert item["subtotal"] == "100.01"
    assert item["quantity"] == "3.0000"
    assert item["unit_price"] == "33.3350"


def test_money_and_quantity_must_be_strings_when_fractional(rab: Rab) -> None:
    assert rab.add(quantity=1.5, unit_price="100").status_code == 422
    assert rab.add(quantity="1", unit_price=99.99).status_code == 422
    assert rab.add(quantity=2, unit_price=1000).status_code == 201  # integers are exact


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"unit_price": "-5"},
        {"unit_price": "1.00001"},
        {"name": ""},
        {"unit": ""},
        {"item_type": "magic"},
        {"price_source_type": "catalog"},  # a source type without a price
    ],
)
def test_item_validation(rab: Rab, body: Json) -> None:
    assert rab.add(**body).status_code == 422


def test_unpriced_items_are_saved_but_block_submission(rab: Rab) -> None:
    ok(rab.add(name="Kabel", quantity="100", unit="m"), 201)
    version = rab.version()
    assert version["totals"]["unpriced_items"] == 1
    assert version["items"][0]["subtotal"] is None

    response = rab.act("submit")
    assert response.status_code == 422
    issues = response.json()["error"]["details"]["issues"]
    assert any(i["code"] == "missing_price" for i in issues)
    assert rab.version()["status"] == "draft"


def test_update_and_delete_item_with_row_version(rab: Rab) -> None:
    item = ok(rab.add(name="Pasir", quantity="2", unit="m3", unit_price="250000"), 201)["items"][0]
    url = rab.url(suffix=f"/items/{item['id']}")
    body = {
        "name": "Pasir beton",
        "quantity": "3",
        "unit": "m3",
        "unit_price": "250000",
        "price_source": "Toko A",
        "row_version": item["row_version"],
    }

    first = ok(rab.browser.put(url, json=body))
    stale = rab.browser.put(url, json={**body, "quantity": "4"})

    assert first["totals"]["subtotal"] == "750000.00"
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    new_row_version = first["items"][0]["row_version"]
    assert rab.browser.delete(url, params={"row_version": item["row_version"]}).status_code == 409
    after_delete = ok(rab.browser.delete(url, params={"row_version": new_row_version}))
    assert after_delete["items"] == [] and after_delete["totals"]["grand_total"] == "0.00"


def test_header_requires_current_lock_version(rab: Rab) -> None:
    version = rab.version()
    ok(rab.add(unit_price="100"), 201)  # bumps lock_version via totals
    stale = rab.browser.patch(
        rab.url(), json={"lock_version": version["lock_version"], "notes": "x"}
    )
    assert stale.status_code == 409


def test_fixed_discount_cannot_exceed_subtotal(rab: Rab) -> None:
    item = ok(rab.add(unit_price="1000"), 201)
    too_big = rab.browser.patch(
        rab.url(),
        json={
            "lock_version": item["lock_version"],
            "discount_type": "amount",
            "discount_value": "1500",
        },
    )
    assert too_big.status_code == 422
    assert "melebihi subtotal" in too_big.json()["error"]["message"]


def test_tax_label_and_rate_go_together(rab: Rab) -> None:
    version = rab.version()
    response = rab.browser.patch(
        rab.url(), json={"lock_version": version["lock_version"], "tax_rate_percent": None}
    )
    assert response.status_code == 422
    cleared = ok(
        rab.browser.patch(
            rab.url(),
            json={
                "lock_version": version["lock_version"],
                "tax_label": None,
                "tax_rate_percent": None,
            },
        )
    )
    assert cleared["totals"]["tax_amount"] == "0.00"
    assert any(i["code"] == "no_tax" for i in cleared["issues"])


# --------------------------------------------------------------------------- workflow


def test_full_approval_flow_with_records(
    db_session: Session, tenant: Tenant, rab: Rab, login_as: LoginAs
) -> None:
    priced_rab(rab)
    approver = login_as(make_user(db_session, tenant.org, Role.APPROVER))

    submitted = ok(rab.act("submit", note="Mohon dicek"))
    assert submitted["status"] == "in_review"
    assert submitted["editable"] is False
    assert submitted["submitted_by"]["id"] == str(tenant.owner.id)
    # Locked while in review.
    assert rab.add(unit_price="1").status_code == 409

    approved = ok(rab.act("approve", browser=approver, note="OK"))
    assert approved["status"] == "approved"
    assert [a["action"] for a in approved["approvals"]] == ["submitted", "approved"]
    assert (
        approved["approvals"][1]["actor"]["full_name"]
        == approver.get("/api/v1/auth/me").json()["user"]["full_name"]
    )
    assert approved["decided_by"] is not None
    assert approved["allowed_actions"] == []
    assert approved["can_create_version"] is False  # approvers do not author
    assert rab.version()["can_create_version"] is True  # the owner may start v2

    # Approved versions are immutable.
    assert rab.add(unit_price="1").status_code == 409
    assert (
        rab.browser.patch(
            rab.url(), json={"lock_version": approved["lock_version"], "notes": "x"}
        ).status_code
        == 409
    )

    records = (
        db_session.execute(select(ApprovalRecord).order_by(ApprovalRecord.created_at))
        .scalars()
        .all()
    )
    assert [(r.from_status, r.to_status) for r in records] == [
        ("draft", "in_review"),
        ("in_review", "approved"),
    ]


def test_reject_requires_note_and_reopen_returns_to_draft(
    db_session: Session, tenant: Tenant, rab: Rab, login_as: LoginAs
) -> None:
    priced_rab(rab)
    approver = login_as(make_user(db_session, tenant.org, Role.APPROVER))
    ok(rab.act("submit"))

    assert rab.act("reject", browser=approver).status_code == 422
    rejected = ok(rab.act("reject", browser=approver, note="Harga semen terlalu tinggi"))
    assert rejected["status"] == "rejected"
    assert rejected["approvals"][-1]["note"] == "Harga semen terlalu tinggi"

    reopened = ok(rab.act("reopen"))
    assert reopened["status"] == "draft" and reopened["editable"] is True
    assert reopened["decided_by"] is None


def test_withdraw_and_invalid_transitions(rab: Rab) -> None:
    priced_rab(rab)
    assert rab.act("approve").status_code == 409  # draft cannot be approved
    ok(rab.act("submit"))
    assert rab.act("submit").status_code == 409  # already in review
    assert ok(rab.act("withdraw"))["status"] == "draft"
    assert rab.act("reopen").status_code == 409
    assert rab.act("teleport").status_code == 422


def test_new_version_copies_items_and_supersedes_on_approval(
    db_session: Session, tenant: Tenant, rab: Rab, login_as: LoginAs
) -> None:
    priced_rab(rab)
    approver = login_as(make_user(db_session, tenant.org, Role.APPROVER))
    ok(rab.act("submit"))
    ok(rab.act("approve", browser=approver))

    v2 = ok(rab.browser.post(f"/api/v1/rab/{rab.id}/versions", json={}), 201)
    assert v2["version_no"] == 2 and v2["status"] == "draft"
    assert v2["based_on_version_id"] == rab.version(1)["id"]
    assert [i["name"] for i in v2["items"]] == ["Semen", "Tukang"]
    assert v2["totals"] == rab.version(1)["totals"]
    # Only one open version at a time.
    assert rab.browser.post(f"/api/v1/rab/{rab.id}/versions", json={}).status_code == 409

    semen = v2["items"][0]
    ok(
        rab.browser.put(
            rab.url(2, f"/items/{semen['id']}"),
            json={
                **{k: semen[k] for k in ("name", "quantity", "unit", "item_type")},
                "unit_price": "70000",
                "price_source": "Toko B",
                "row_version": semen["row_version"],
            },
        )
    )
    ok(rab.act("submit", version=2))
    ok(rab.act("approve", version=2, browser=approver))

    assert rab.version(1)["status"] == "archived"
    assert rab.version(1)["approvals"][-1]["action"] == "superseded"
    assert rab.version(2)["status"] == "approved"
    assert rab.version(1)["items"][0]["unit_price"] == "65000.0000"  # v1 untouched


def test_compare_versions(db_session: Session, tenant: Tenant, rab: Rab, login_as: LoginAs) -> None:
    priced_rab(rab)
    approver = login_as(make_user(db_session, tenant.org, Role.APPROVER))
    ok(rab.act("submit"))
    ok(rab.act("approve", browser=approver))
    v2 = ok(rab.browser.post(f"/api/v1/rab/{rab.id}/versions", json={}), 201)
    tukang = v2["items"][1]
    rab.browser.delete(
        rab.url(2, f"/items/{tukang['id']}"), params={"row_version": tukang["row_version"]}
    )
    ok(rab.add(2, name="Besi", quantity="20", unit="batang", unit_price="95000"), 201)

    diff = ok(rab.browser.get(f"/api/v1/rab/{rab.id}/compare", params={"from": 1, "to": 2}))

    kinds = {line["name"]: line["kind"] for line in diff["lines"]}
    assert kinds == {"Semen": "unchanged", "Besi": "added", "Tukang": "removed"}
    assert diff["grand_total_delta"] == str(
        Decimal(diff["after_totals"]["grand_total"]) - Decimal(diff["before_totals"]["grand_total"])
    )
    assert (
        rab.browser.get(f"/api/v1/rab/{rab.id}/compare", params={"from": 1, "to": 1}).status_code
        == 422
    )


def test_archive_draft_and_rejected(rab: Rab) -> None:
    archived = ok(rab.act("archive"))
    assert archived["status"] == "archived"
    assert archived["can_create_version"] is True


def test_duplicate_creates_independent_rab(tenant: Tenant, rab: Rab, project: Any) -> None:
    priced_rab(rab)
    copy = ok(rab.browser.post(f"/api/v1/rab/{rab.id}/duplicate", json={}), 201)

    assert copy["number"] == f"RAB-{YEAR}-0002"
    assert copy["title"] == "RAB Gudang (salinan)"
    copy_v1 = ok(rab.browser.get(f"/api/v1/rab/{copy['id']}/versions/1"))
    assert [i["name"] for i in copy_v1["items"]] == ["Semen", "Tukang"]
    assert copy_v1["totals"] == rab.version()["totals"]
    assert {i["id"] for i in copy_v1["items"]}.isdisjoint({i["id"] for i in rab.version()["items"]})


def test_delete_rules(
    db_session: Session, tenant: Tenant, rab: Rab, login_as: LoginAs, project: Any
) -> None:
    # A project with a RAB cannot be deleted.
    assert tenant.browser.delete(f"/api/v1/projects/{project.id}").status_code == 409

    priced_rab(rab)
    approver = login_as(make_user(db_session, tenant.org, Role.APPROVER))
    ok(rab.act("submit"))
    assert rab.browser.delete(f"/api/v1/rab/{rab.id}").status_code == 409  # in review
    ok(rab.act("approve", browser=approver))
    assert rab.browser.delete(f"/api/v1/rab/{rab.id}").status_code == 409  # was approved

    draft_only = Rab(
        tenant.browser,
        ok(tenant.browser.post(f"/api/v1/projects/{project.id}/rab", json={"title": "Coba"}), 201),
    )
    assert tenant.browser.delete(f"/api/v1/rab/{draft_only.id}").status_code == 204


def test_no_new_rab_for_finished_projects(db_session: Session, tenant: Tenant) -> None:
    done = make_project(db_session, tenant.org, status=ProjectStatus.COMPLETED)
    response = tenant.browser.post(f"/api/v1/projects/{done.id}/rab", json={"title": "Telat"})
    assert response.status_code == 409


def test_list_filters_and_latest_status(tenant: Tenant, rab: Rab, project: Any) -> None:
    priced_rab(rab)
    ok(rab.act("submit"))
    ok(tenant.browser.post(f"/api/v1/projects/{project.id}/rab", json={"title": "Kedua"}), 201)

    all_rabs = ok(tenant.browser.get("/api/v1/rab"))
    in_review = ok(tenant.browser.get("/api/v1/rab", params={"status": "in_review"}))
    by_project = ok(tenant.browser.get(f"/api/v1/projects/{project.id}/rab"))
    search = ok(tenant.browser.get("/api/v1/rab", params={"q": "gudang"}))

    assert all_rabs["total"] == 2 and by_project["total"] == 2
    assert [r["title"] for r in in_review["items"]] == ["RAB Gudang"]
    assert in_review["items"][0]["grand_total"] == "1554000.00"
    assert [r["title"] for r in search["items"]] == ["RAB Gudang"]


def test_pending_queue_and_dashboard(
    db_session: Session, tenant: Tenant, rab: Rab, login_as: LoginAs
) -> None:
    priced_rab(rab)
    ok(rab.act("submit"))
    approver = login_as(make_user(db_session, tenant.org, Role.APPROVER))

    queue = ok(approver.get("/api/v1/approvals/pending"))
    summary = ok(tenant.browser.get("/api/v1/dashboard/summary"))

    assert [(q["number"], q["version_no"]) for q in queue] == [(rab.number, 1)]
    assert summary["rab"]["in_review"] == 1
    ok(rab.act("approve", browser=approver))
    summary = ok(tenant.browser.get("/api/v1/dashboard/summary"))
    assert summary["rab"]["approved_total"] == [
        {"currency": "IDR", "total": "1554000.00", "count": 1}
    ]


# --------------------------------------------------------------------------- permissions


def test_estimator_writes_but_cannot_approve_and_viewer_reads_only(
    db_session: Session, tenant: Tenant, rab: Rab, login_as: LoginAs
) -> None:
    estimator = login_as(make_user(db_session, tenant.org, Role.ESTIMATOR))
    viewer = login_as(make_user(db_session, tenant.org, Role.VIEWER))

    assert rab.add(unit_price="100").status_code == 201
    as_estimator = Rab(estimator, {"id": rab.id, "number": rab.number})
    assert as_estimator.add(unit_price="200").status_code == 201
    ok(as_estimator.act("submit"))
    assert as_estimator.act("approve").status_code == 403
    assert rab.version(browser=estimator)["allowed_actions"] == ["withdraw"]

    as_viewer = Rab(viewer, {"id": rab.id, "number": rab.number})
    assert rab.version(browser=viewer)["allowed_actions"] == []
    assert as_viewer.add(unit_price="1").status_code == 403
    assert as_viewer.act("withdraw").status_code == 403
    assert viewer.get("/api/v1/approvals/pending").status_code == 403


def test_other_organization_cannot_touch_rab(rab: Rab, other_tenant: Tenant, project: Any) -> None:
    item = ok(rab.add(unit_price="100"), 201)["items"][0]
    b = other_tenant.browser
    paths = [
        b.get(f"/api/v1/rab/{rab.id}"),
        b.get(rab.url()),
        b.post(rab.url(suffix="/items"), json={"name": "x", "quantity": "1", "unit": "u"}),
        b.put(
            rab.url(suffix=f"/items/{item['id']}"),
            json={"name": "x", "quantity": "1", "unit": "u", "row_version": 1},
        ),
        b.post(rab.url(suffix="/transitions/submit"), json={}),
        b.post(f"/api/v1/rab/{rab.id}/duplicate", json={}),
        b.get(f"/api/v1/rab/{rab.id}/compare", params={"from": 1, "to": 2}),
        b.post(f"/api/v1/projects/{project.id}/rab", json={"title": "Bajak"}),
    ]
    assert [r.status_code for r in paths] == [404] * len(paths)
    assert ok(b.get("/api/v1/rab"))["total"] == 0


def test_rab_changes_are_audited(db_session: Session, tenant: Tenant, rab: Rab) -> None:
    priced_rab(rab)
    ok(rab.act("submit"))
    actions = set(
        db_session.execute(
            select(AuditLog.action).where(AuditLog.organization_id == tenant.org.id)
        ).scalars()
    )
    assert {"rab.create", "rab_item.create", "rab_version.submit"} <= actions


def test_database_refuses_a_second_open_version(db_session: Session, rab: Rab) -> None:
    """The partial unique index backs the service rule even if code paths race."""
    from sqlalchemy.exc import IntegrityError

    from app.modules.rab.models import RabStatus, RabVersion

    first = db_session.execute(select(RabVersion).where(RabVersion.version_no == 1)).scalar_one()
    savepoint = db_session.begin_nested()
    db_session.add(
        RabVersion(
            organization_id=first.organization_id,
            rab_id=first.rab_id,
            version_no=2,
            status=RabStatus.DRAFT,
            currency="IDR",
        )
    )
    with pytest.raises(IntegrityError, match="uq_rab_versions_one_open"):
        db_session.flush()
    savepoint.rollback()
