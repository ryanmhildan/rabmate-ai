"""SPK and BAST through the API: sources, workflow, issuance, delivery rule, isolation."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.identity.permissions import Role
from tests.factories import LoginAs, Tenant, make_client, make_user
from tests.test_billing_api import (
    TODAY,
    YEAR,
    Roles,
    act,
    issued_quotation,
    network_rab,
    pdf_text,
)
from tests.test_rab_api import Rab, ok


@pytest.fixture
def roles(db_session: Session, tenant: Tenant, login_as: LoginAs) -> Roles:
    return Roles(db_session, tenant, login_as)


@pytest.fixture
def rab(db_session: Session, tenant: Tenant) -> Rab:
    client = make_client(db_session, tenant.org, name="CV Klien Makmur")
    return network_rab(db_session, tenant, str(client.id))


@pytest.fixture
def pm(db_session: Session, tenant: Tenant, login_as: LoginAs) -> TestClient:
    return login_as(make_user(db_session, tenant.org, Role.PROJECT_MANAGER))


SPK_FIELDS = {
    "title": "Instalasi jaringan kantor",
    "start_date": str(TODAY),
    "end_date": str(TODAY + timedelta(days=30)),
    "location": "Gedung A lt. 2",
    "scope": "Penarikan kabel dan instalasi titik jaringan sesuai penawaran.",
    "client_signatory_name": "Budi Santoso",
    "client_signatory_title": "Direktur",
    "company_signatory_name": "Sari Wulandari",
    "company_signatory_title": "Manajer Proyek",
}


def create_spk(pm: TestClient, quotation: dict[str, Any]) -> dict[str, Any]:
    spk: dict[str, Any] = ok(pm.post("/api/v1/spk", json={"quotation_id": quotation["id"]}), 201)
    return spk


def fill_spk(pm: TestClient, spk: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body = {**SPK_FIELDS, "terms": spk["terms"], "version": spk["version"], **overrides}
    result: dict[str, Any] = ok(pm.patch(f"/api/v1/spk/{spk['id']}", json=body))
    return result


def issued_spk(
    roles: Roles, pm: TestClient, rab: Rab, draft: dict[str, Any] | None = None
) -> dict[str, Any]:
    spk = fill_spk(pm, draft or create_spk(pm, issued_quotation(roles, rab)))
    ok(act(pm, "spk", spk, "submit"))
    ok(act(roles.approver, "spk", spk, "approve"))
    ok(roles.finance.post(f"/api/v1/spk/{spk['id']}/issue"), 201)
    result: dict[str, Any] = ok(pm.get(f"/api/v1/spk/{spk['id']}"))
    return result


def contract(browser: TestClient, spk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Progress rows by item unit ("m" = kabel 305, "titik" = instalasi 48)."""
    rows = ok(browser.get(f"/api/v1/spk/{spk['id']}/progress"))["items"]
    return {row["unit"]: row for row in rows}


def bast_body(
    bast: dict[str, Any], items: list[dict[str, Any]], **overrides: Any
) -> dict[str, Any]:
    return {
        "version": bast["version"],
        "title": bast["title"],
        "handover_date": str(TODAY),
        "location": "Gedung A lt. 2",
        "delivered_by_name": "Sari Wulandari",
        "delivered_by_title": "Manajer Proyek",
        "received_by_name": "Budi Santoso",
        "received_by_title": "Direktur",
        "items": items,
        **overrides,
    }


def line(row: dict[str, Any], quantity: str, **overrides: Any) -> dict[str, Any]:
    return {
        "rab_item_id": row["rab_item_id"],
        "description": row["name"],
        "quantity": quantity,
        "unit": row["unit"],
        **overrides,
    }


def new_bast(pm: TestClient, spk: dict[str, Any], kind: str = "partial", **extra: Any) -> Any:
    return pm.post("/api/v1/bast", json={"spk_id": spk["id"], "kind": kind, **extra})


def save_bast(pm: TestClient, bast: dict[str, Any], items: list[dict[str, Any]], **kw: Any) -> Any:
    return pm.patch(f"/api/v1/bast/{bast['id']}", json=bast_body(bast, items, **kw))


def approve_bast(roles: Roles, pm: TestClient, bast: dict[str, Any]) -> None:
    ok(act(pm, "bast", bast, "submit"))
    ok(act(roles.approver, "bast", bast, "approve"))


def locs(response: Any) -> list[list[Any]]:
    assert response.status_code == 422, response.text
    return [d["loc"] for d in response.json()["error"]["details"]]


# --------------------------------------------------------------------------- SPK


def test_spk_from_accepted_quotation_review_and_issue(
    roles: Roles, pm: TestClient, rab: Rab, db_session: Session
) -> None:
    ok(
        roles.owner.put(
            "/api/v1/document-settings",
            json={"version": 0, "spk_terms": "Ketentuan SPK dari template."},
        )
    )
    pending = issued_quotation(roles, rab, accept=False)
    refused = pm.post("/api/v1/spk", json={"quotation_id": pending["id"]})
    assert refused.status_code == 409
    ok(pm.post(f"/api/v1/quotations/{pending['id']}/response", json={"response": "accepted"}))
    assert ok(pm.get("/api/v1/dashboard/summary"))["workorders"]["accepted_without_spk"] == 1
    quotation = ok(pm.get(f"/api/v1/quotations/{pending['id']}"))
    assert quotation["can_create_spk"] is True
    assert (
        roles.estimator.post("/api/v1/spk", json={"quotation_id": pending["id"]}).status_code == 403
    )

    spk = create_spk(pm, quotation)
    assert spk["status"] == "draft"
    assert spk["number"] is None
    assert spk["contract_value"] == "10779765.00"
    assert spk["taxable_base"] == "9711500.00"
    assert spk["terms"] == "Ketentuan SPK dari template."
    assert [t["total_amount"] for t in spk["payment_terms"]] == [
        "3233929.50",
        "4311906.00",
        "3233929.50",
    ]
    assert spk["quotation"]["number"] == quotation["number"]
    assert pm.post("/api/v1/spk", json={"quotation_id": quotation["id"]}).status_code == 409

    # The quotation is now bound to the SPK.
    quotation = ok(pm.get(f"/api/v1/quotations/{quotation['id']}"))
    assert quotation["spk"]["id"] == spk["id"]
    assert quotation["can_void"] is False
    assert quotation["can_respond"] is False
    assert quotation["can_create_spk"] is False
    assert (
        roles.finance.post(
            f"/api/v1/quotations/{quotation['id']}/void", json={"reason": "x"}
        ).status_code
        == 409
    )
    assert (
        pm.post(
            f"/api/v1/quotations/{quotation['id']}/response", json={"response": "declined"}
        ).status_code
        == 409
    )

    # Nothing is assumed: the parties and the work must be stated before review.
    missing = locs(act(pm, "spk", spk, "submit"))
    assert ["body", "start_date"] in missing
    assert ["body", "client_signatory_name"] in missing
    assert ["body", "company_signatory_name"] in missing
    assert ["body", "scope"] in missing
    backwards = pm.patch(
        f"/api/v1/spk/{spk['id']}",
        json={**SPK_FIELDS, "version": spk["version"], "end_date": str(TODAY - timedelta(days=1))},
    )
    assert ["body", "end_date"] in locs(backwards)
    filled = fill_spk(pm, spk)
    stale = pm.patch(f"/api/v1/spk/{spk['id']}", json={**SPK_FIELDS, "version": spk["version"]})
    assert stale.status_code == 409

    preview = pm.get(f"/api/v1/spk/{spk['id']}/preview.pdf")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/pdf"
    text = pdf_text(preview.content)
    for expected in (
        "SURAT PERINTAH KERJA",
        "PRATINJAU",
        "Budi Santoso",
        "Sari Wulandari",
        "10.779.765",
        "Ketentuan SPK dari template.",
        quotation["number"],
    ):
        assert expected in text, expected

    ok(act(pm, "spk", filled, "submit"))
    assert ok(pm.get("/api/v1/dashboard/summary"))["workorders"]["spk_in_review"] == 1
    assert (
        pm.patch(f"/api/v1/spk/{spk['id']}", json={**SPK_FIELDS, "version": 2}).status_code == 409
    )
    assert act(pm, "spk", filled, "approve").status_code == 403
    assert act(roles.approver, "spk", filled, "reject").status_code == 422  # reason required
    approved = ok(act(roles.approver, "spk", filled, "approve"))
    assert approved["status"] == "approved"
    assert approved["can_issue"] is True  # the approver may also issue
    assert ok(pm.get(f"/api/v1/spk/{spk['id']}"))["can_issue"] is False  # PM may not

    url = f"/api/v1/spk/{spk['id']}/issue"
    assert pm.post(url).status_code == 403
    key = {"Idempotency-Key": f"spk-{spk['id']}"}
    document = ok(roles.finance.post(url, headers=key), 201)
    assert document["doc_type"] == "spk"
    assert document["number"] == f"SPK-{YEAR}-0001"
    assert document["spk_id"] == spk["id"]
    assert document["total_amount"] == "10779765.00"
    replay = roles.finance.post(url, headers=key)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert roles.finance.post(url).status_code == 409

    issued = ok(pm.get(f"/api/v1/spk/{spk['id']}"))
    assert issued["status"] == "issued"
    assert issued["number"] == f"SPK-{YEAR}-0001"
    assert issued["issue_date"] == str(TODAY)
    assert issued["can_create_bast"] is True
    pdf = pm.get(f"/api/v1/documents/{document['id']}/files/pdf")
    assert pdf.status_code == 200
    text = pdf_text(pdf.content)
    assert f"SPK-{YEAR}-0001" in text
    assert "PRATINJAU" not in text

    actions = set(
        db_session.execute(
            select(AuditLog.action).where(AuditLog.entity_id == uuid.UUID(spk["id"]))
        ).scalars()
    )
    assert {"spk.create", "spk.update", "spk.submit", "spk.approve"} <= actions


def test_spk_delete_void_and_permissions(roles: Roles, pm: TestClient, rab: Rab) -> None:
    quotation = issued_quotation(roles, rab)
    draft = create_spk(pm, quotation)
    assert roles.viewer.get(f"/api/v1/spk/{draft['id']}").status_code == 200
    assert (
        roles.viewer.patch(
            f"/api/v1/spk/{draft['id']}", json={**SPK_FIELDS, "version": draft["version"]}
        ).status_code
        == 403
    )
    assert roles.viewer.delete(f"/api/v1/spk/{draft['id']}").status_code == 403
    assert pm.delete(f"/api/v1/spk/{draft['id']}").status_code == 204
    assert pm.get(f"/api/v1/spk/{draft['id']}").status_code == 404

    spk = fill_spk(pm, create_spk(pm, quotation))
    ok(act(pm, "spk", spk, "submit"))
    ok(act(roles.approver, "spk", spk, "approve"))
    ok(roles.finance.post(f"/api/v1/spk/{spk['id']}/issue"), 201)
    assert pm.delete(f"/api/v1/spk/{spk['id']}").status_code == 409
    assert pm.post(f"/api/v1/spk/{spk['id']}/void", json={"reason": "x"}).status_code == 403
    voided = ok(roles.finance.post(f"/api/v1/spk/{spk['id']}/void", json={"reason": "Batal"}))
    assert voided["status"] == "void"
    docs = ok(roles.owner.get(f"/api/v1/documents?spk_id={spk['id']}"))["items"]
    assert [d["status"] for d in docs] == ["void"]
    # A voided SPK frees the quotation for a new one.
    assert ok(pm.get(f"/api/v1/quotations/{quotation['id']}"))["can_create_spk"] is True


# --------------------------------------------------------------------------- BAST


def test_bast_lines_follow_the_contract(roles: Roles, pm: TestClient, rab: Rab) -> None:
    draft_spk = create_spk(pm, issued_quotation(roles, rab))
    assert new_bast(pm, draft_spk).status_code == 409  # SPK not issued

    spk = issued_spk(roles, pm, rab, draft_spk)
    rows = contract(pm, spk)
    kabel, titik = rows["m"], rows["titik"]
    assert (kabel["contract_quantity"], titik["contract_quantity"]) == ("305.0000", "48.0000")

    prefilled = ok(new_bast(pm, spk, prefill_remaining=True), 201)
    assert [(i["quantity"], i["unit"]) for i in prefilled["items"]] == [
        ("305.0000", "m"),
        ("48.0000", "titik"),
    ]
    assert pm.delete(f"/api/v1/bast/{prefilled['id']}").status_code == 204

    bast = ok(new_bast(pm, spk), 201)
    assert bast["items"] == []
    assert bast["status"] == "draft"
    assert ["body", "items"] in locs(act(pm, "bast", bast, "submit"))

    assert ["body", "items", 0, "quantity"] in locs(save_bast(pm, bast, [line(kabel, "305.5")]))
    assert ["body", "items", 0, "unit"] in locs(
        save_bast(pm, bast, [line(kabel, "10", unit="roll")])
    )
    assert ["body", "items", 1, "rab_item_id"] in locs(
        save_bast(pm, bast, [line(kabel, "10"), line(kabel, "5")])
    )
    foreign = {**line(kabel, "1"), "rab_item_id": str(uuid.uuid4())}
    assert ["body", "items", 0, "rab_item_id"] in locs(save_bast(pm, bast, [foreign]))
    future = save_bast(pm, bast, [line(kabel, "1")], handover_date=str(TODAY + timedelta(days=1)))
    assert ["body", "handover_date"] in locs(future)

    saved = ok(
        save_bast(
            pm,
            bast,
            [
                line(kabel, "200", condition="Terpasang, diuji continuity"),
                line(titik, "20"),
                {"description": "Patch panel tambahan", "quantity": "1", "unit": "unit"},
            ],
        )
    )
    assert [i["position"] for i in saved["items"]] == [1, 2, 3]
    assert saved["items"][2]["rab_item_id"] is None
    assert contract(pm, spk)["m"]["pending_quantity"] == "200.0000"

    approve_bast(roles, pm, saved)
    preview = pdf_text(pm.get(f"/api/v1/bast/{bast['id']}/preview.pdf").content)
    for expected in ("BERITA ACARA SERAH TERIMA", "PRATINJAU", "Kumulatif", spk["number"]):
        assert expected in preview, expected
    document = ok(roles.finance.post(f"/api/v1/bast/{bast['id']}/issue"), 201)
    assert document["doc_type"] == "bast"
    assert document["number"] == f"BAST-{YEAR}-0001"
    issued_text = pdf_text(pm.get(f"/api/v1/documents/{document['id']}/files/pdf").content)
    assert f"BAST-{YEAR}-0001" in issued_text
    assert "Terpasang, diuji continuity" in issued_text
    assert "Patch panel tambahan" in issued_text

    rows = contract(pm, spk)
    assert rows["m"]["delivered_quantity"] == "200.0000"
    assert rows["m"]["remaining_quantity"] == "105.0000"
    assert rows["titik"]["remaining_quantity"] == "28.0000"
    assert rows["m"]["pending_quantity"] == "0"


def test_bast_issuance_rechecks_cumulative_volume(roles: Roles, pm: TestClient, rab: Rab) -> None:
    spk = issued_spk(roles, pm, rab)
    kabel = contract(pm, spk)["m"]

    # Two drafts each fit the remaining volume on their own, but not together.
    first = ok(new_bast(pm, spk), 201)
    second = ok(new_bast(pm, spk), 201)
    first = ok(save_bast(pm, first, [line(kabel, "200")]))
    second = ok(save_bast(pm, second, [line(kabel, "200")]))
    approve_bast(roles, pm, first)
    approve_bast(roles, pm, second)
    ok(roles.finance.post(f"/api/v1/bast/{first['id']}/issue"), 201)
    refused = roles.finance.post(f"/api/v1/bast/{second['id']}/issue")
    assert ["body", "items", 0, "quantity"] in locs(refused)
    assert ok(pm.get(f"/api/v1/bast/{second['id']}"))["status"] == "approved"

    summary = ok(pm.get("/api/v1/dashboard/summary"))["workorders"]
    assert summary == {
        "accepted_without_spk": 0,
        "spk_in_review": 0,
        "spk_open": 1,
        "bast_in_review": 0,
    }

    # Final handover: only one per SPK.
    final = ok(new_bast(pm, spk, "final"), 201)
    assert final["kind"] == "final"
    assert new_bast(pm, spk, "final").status_code == 409
    assert ok(pm.get(f"/api/v1/spk/{spk['id']}/progress"))["final_bast"]["id"] == final["id"]

    # The SPK cannot be voided while BASTs depend on it; voiding a BAST releases its volume.
    assert (
        roles.finance.post(f"/api/v1/spk/{spk['id']}/void", json={"reason": "x"}).status_code == 409
    )
    assert pm.post(f"/api/v1/bast/{first['id']}/void", json={"reason": "x"}).status_code == 403
    voided = ok(roles.finance.post(f"/api/v1/bast/{first['id']}/void", json={"reason": "Salah"}))
    assert voided["status"] == "void"
    assert contract(pm, spk)["m"]["delivered_quantity"] == "0"
    ok(roles.finance.post(f"/api/v1/bast/{second['id']}/issue"), 201)
    docs = ok(roles.owner.get(f"/api/v1/documents?bast_id={first['id']}"))["items"]
    assert [d["status"] for d in docs] == ["void"]


def test_spk_bast_isolation(roles: Roles, pm: TestClient, rab: Rab, other_tenant: Tenant) -> None:
    spk = issued_spk(roles, pm, rab)
    bast = ok(new_bast(pm, spk), 201)
    stranger = other_tenant.browser
    for url in (
        f"/api/v1/spk/{spk['id']}",
        f"/api/v1/spk/{spk['id']}/progress",
        f"/api/v1/spk/{spk['id']}/preview.pdf",
        f"/api/v1/bast/{bast['id']}",
        f"/api/v1/bast/{bast['id']}/preview.pdf",
    ):
        assert stranger.get(url).status_code == 404, url
    assert ok(stranger.get("/api/v1/spk"))["total"] == 0
    assert ok(stranger.get("/api/v1/bast"))["total"] == 0
    assert (
        stranger.post("/api/v1/spk", json={"quotation_id": spk["quotation"]["id"]}).status_code
        == 404
    )
    assert new_bast(stranger, spk).status_code == 404
    assert stranger.post(f"/api/v1/bast/{bast['id']}/void", json={"reason": "x"}).status_code == 404
    assert ok(pm.get(f"/api/v1/bast?spk_id={spk['id']}"))["total"] == 1
