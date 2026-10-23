"""Price catalog API: items, history, verification, candidates, RAB linkage, isolation."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.identity.permissions import Role
from app.modules.pricing.models import PriceObservation, VerificationStatus
from tests.factories import LoginAs, Tenant, make_project, make_user

TODAY = date.today().isoformat()


def ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def make_item(browser: TestClient, **overrides: Any) -> Any:
    body = {"name": "Kabel UTP Cat6", "unit": "m", "category": "Jaringan", **overrides}
    return ok(browser.post("/api/v1/price-catalog", json=body), 201)


def add_price(browser: TestClient, item_id: str, **overrides: Any) -> Any:
    body = {
        "price": "4500",
        "observed_at": TODAY,
        "source_reference": "Penawaran 12/X",
        **overrides,
    }
    return ok(browser.post(f"/api/v1/price-catalog/{item_id}/observations", json=body), 201)


@pytest.fixture
def approver(db_session: Session, tenant: Tenant, login_as: LoginAs) -> TestClient:
    return login_as(make_user(db_session, tenant.org, Role.APPROVER))


def verify(
    browser: TestClient, observation_id: str, status: str = "verified", note: str | None = None
) -> Any:
    return browser.post(
        f"/api/v1/price-observations/{observation_id}/verification",
        json={"status": status, "note": note},
    )


# --------------------------------------------------------------------------- items & history


def test_item_with_initial_price_starts_unverified(tenant: Tenant) -> None:
    item = make_item(
        tenant.browser,
        code="NET-01",
        brand="Belden",
        initial_price={
            "price": "4500.75",
            "observed_at": TODAY,
            "source_url": "https://toko.example/x",
        },
    )

    assert item["code"] == "NET-01"
    assert len(item["observations"]) == 1
    observation = item["observations"][0]
    assert observation["price"] == "4500.7500"
    assert observation["unit"] == "m"
    assert observation["verification_status"] == "unverified"
    assert item["prices"]["latest_verified"] is None
    assert item["prices"]["latest_any"]["id"] == observation["id"]


def test_history_is_ordered_and_summaries_separate_verified(
    tenant: Tenant, approver: TestClient
) -> None:
    item = make_item(tenant.browser)
    old = add_price(tenant.browser, item["id"], price="4300", observed_at="2026-01-10")
    new = add_price(tenant.browser, item["id"], price="4700", observed_at="2026-09-01")
    ok(verify(approver, old["id"]))

    detail = ok(tenant.browser.get(f"/api/v1/price-catalog/{item['id']}"))
    assert [o["price"] for o in detail["observations"]] == ["4700.0000", "4300.0000"]
    assert detail["prices"]["latest_verified"]["id"] == old["id"]
    assert detail["prices"]["latest_any"]["id"] == new["id"]
    assert detail["prices"]["observation_count"] == 2

    listed = ok(tenant.browser.get("/api/v1/price-catalog", params={"q": "utp"}))["items"][0]
    assert listed["prices"]["latest_verified"]["price"] == "4300.0000"


@pytest.mark.parametrize(
    "body",
    [
        {"price": 4500.5},  # float JSON number: precision risk
        {"price": "-1"},
        {"price": "1.00001"},
        {"currency": "idr"},
        {"source_url": "javascript:alert(1)"},
        {"source_type": "import"},  # only the importer may create these
        {"observed_at": "2026-10-10", "valid_until": "2026-10-01"},
        {"unit": "roll"},  # item is priced per m
    ],
)
def test_observation_validation(tenant: Tenant, body: dict[str, Any]) -> None:
    item = make_item(tenant.browser)
    response = tenant.browser.post(
        f"/api/v1/price-catalog/{item['id']}/observations",
        json={"price": "4500", "observed_at": TODAY, **body},
    )
    assert response.status_code == 422, (body, response.text)


def test_unit_cannot_change_once_prices_exist(tenant: Tenant) -> None:
    item = make_item(tenant.browser)
    body = {"name": item["name"], "unit": "roll", "version": item["version"]}
    ok(tenant.browser.patch(f"/api/v1/price-catalog/{item['id']}", json=body))  # no prices yet
    add_price(tenant.browser, item["id"], unit="roll")
    changed = ok(tenant.browser.get(f"/api/v1/price-catalog/{item['id']}"))
    response = tenant.browser.patch(
        f"/api/v1/price-catalog/{item['id']}",
        json={"name": item["name"], "unit": "m", "version": changed["version"]},
    )
    assert response.status_code == 409


def test_duplicate_code_and_version_conflict(tenant: Tenant) -> None:
    make_item(tenant.browser, code="A-1")
    assert (
        tenant.browser.post(
            "/api/v1/price-catalog", json={"code": "A-1", "name": "X", "unit": "m"}
        ).status_code
        == 409
    )
    item = make_item(tenant.browser, code="B-1")
    body = {"name": "Baru", "unit": "m", "version": item["version"]}
    ok(tenant.browser.patch(f"/api/v1/price-catalog/{item['id']}", json=body))
    assert tenant.browser.patch(f"/api/v1/price-catalog/{item['id']}", json=body).status_code == 409


# --------------------------------------------------------------------------- verification


def test_price_without_source_cannot_be_verified(tenant: Tenant, approver: TestClient) -> None:
    item = make_item(tenant.browser)
    bare = add_price(tenant.browser, item["id"], source_reference=None)

    response = verify(approver, bare["id"])

    assert response.status_code == 422
    assert "tanpa sumber" in response.json()["error"]["message"]


def test_database_also_refuses_verified_without_source(db_session: Session, tenant: Tenant) -> None:
    item = make_item(tenant.browser)
    bare = add_price(tenant.browser, item["id"], source_reference=None)
    observation = db_session.get(PriceObservation, bare["id"])
    assert observation is not None
    savepoint = db_session.begin_nested()
    observation.verification_status = VerificationStatus.VERIFIED
    observation.verified_at = observation.created_at
    with pytest.raises(IntegrityError, match="verified_requires_source"):
        db_session.flush()
    savepoint.rollback()


def test_verification_transitions_permissions_and_audit(
    db_session: Session, tenant: Tenant, approver: TestClient, login_as: LoginAs
) -> None:
    estimator = login_as(make_user(db_session, tenant.org, Role.ESTIMATOR))
    item = make_item(estimator)
    price = add_price(estimator, item["id"])

    assert verify(estimator, price["id"]).status_code == 403  # authors cannot verify
    verified = ok(verify(approver, price["id"], note="Cocok dengan penawaran"))
    assert verified["verification_status"] == "verified"
    assert verified["verified_by"]["full_name"]
    assert verify(approver, price["id"]).status_code == 409  # already verified
    assert verify(approver, price["id"], "rejected").status_code == 422  # note required
    rejected = ok(verify(approver, price["id"], "rejected", "Harga kedaluwarsa"))
    assert rejected["verification_status"] == "rejected"
    assert verify(approver, price["id"]).status_code == 409  # rejected is final

    actions = set(db_session.execute(select(AuditLog.action)).scalars())
    assert {
        "price_observation.create",
        "price_observation.verify",
        "price_observation.reject",
    } <= actions


def test_viewer_reads_but_cannot_write(
    db_session: Session, tenant: Tenant, login_as: LoginAs
) -> None:
    viewer = login_as(make_user(db_session, tenant.org, Role.VIEWER))
    item = make_item(tenant.browser)
    assert viewer.get(f"/api/v1/price-catalog/{item['id']}").status_code == 200
    assert viewer.post("/api/v1/price-catalog", json={"name": "x", "unit": "m"}).status_code == 403
    assert viewer.post("/api/v1/suppliers", json={"name": "x"}).status_code == 403


# --------------------------------------------------------------------------- suppliers


def test_suppliers_and_supplier_as_source(
    tenant: Tenant, approver: TestClient, other_tenant: Tenant
) -> None:
    supplier = ok(
        tenant.browser.post("/api/v1/suppliers", json={"name": "Toko Jaya", "city": "Bandung"}), 201
    )
    foreign = ok(other_tenant.browser.post("/api/v1/suppliers", json={"name": "Asing"}), 201)
    item = make_item(tenant.browser)

    with_supplier = add_price(
        tenant.browser, item["id"], source_reference=None, supplier_id=supplier["id"]
    )
    assert with_supplier["supplier"]["name"] == "Toko Jaya"
    assert ok(verify(approver, with_supplier["id"]))["verification_status"] == "verified"

    response = tenant.browser.post(
        f"/api/v1/price-catalog/{item['id']}/observations",
        json={"price": "1", "observed_at": TODAY, "supplier_id": foreign["id"]},
    )
    assert response.status_code == 404  # another org's supplier does not exist here

    updated = ok(
        tenant.browser.patch(
            f"/api/v1/suppliers/{supplier['id']}",
            json={"name": "Toko Jaya Abadi", "version": supplier["version"], "is_active": False},
        )
    )
    assert updated["is_active"] is False
    assert ok(tenant.browser.get("/api/v1/suppliers", params={"is_active": "false"}))["total"] == 1


# --------------------------------------------------------------------------- candidates


def test_candidates_rank_and_explain(tenant: Tenant, approver: TestClient) -> None:
    exact = make_item(tenant.browser, name="Kabel UTP Cat6", brand="Belden")
    verify_id = add_price(tenant.browser, exact["id"])["id"]
    ok(verify(approver, verify_id))
    other_size = make_item(tenant.browser, name="Kabel UTP Cat5e")
    add_price(tenant.browser, other_size["id"], price="3000")
    per_roll = make_item(tenant.browser, name="Kabel UTP Cat6 roll 305m", unit="roll")
    add_price(tenant.browser, per_roll["id"], price="1200000")
    unrelated = make_item(tenant.browser, name="Cat tembok putih", unit="kaleng")
    add_price(tenant.browser, unrelated["id"], price="150000")
    make_item(tenant.browser, name="Kabel UTP Cat6 tanpa harga")  # no observation → no candidate

    found = ok(
        tenant.browser.get(
            "/api/v1/price-catalog/candidates", params={"name": "Kabel UTP Cat6", "unit": "m"}
        )
    )

    names = [c["name"] for c in found]
    assert names[0] == "Kabel UTP Cat6"
    assert found[0]["level"] == "high" and found[0]["verified"] is True
    assert "Kabel UTP Cat6 tanpa harga" not in names
    roll = next(c for c in found if c["unit"] == "roll")
    assert roll["unit_compatible"] is False and roll["level"] == "low"
    cat5e = next(c for c in found if c["name"] == "Kabel UTP Cat5e")
    assert cat5e["level"] != "high"
    assert any("6" in w for w in cat5e["warnings"])


def test_candidates_include_approved_rab_history(
    db_session: Session, tenant: Tenant, approver: TestClient
) -> None:
    project = make_project(db_session, tenant.org)
    rab = ok(tenant.browser.post(f"/api/v1/projects/{project.id}/rab", json={"title": "Lama"}), 201)
    base = f"/api/v1/rab/{rab['id']}/versions/1"
    ok(
        tenant.browser.post(
            f"{base}/items",
            json={
                "name": "Pasir beton",
                "quantity": "5",
                "unit": "m3",
                "unit_price": "350000",
                "price_source": "Survei",
            },
        ),
        201,
    )
    ok(tenant.browser.post(f"{base}/transitions/submit", json={}))
    ok(approver.post(f"{base}/transitions/approve", json={}))

    found = ok(
        tenant.browser.get(
            "/api/v1/price-catalog/candidates", params={"name": "pasir beton", "unit": "m3"}
        )
    )

    history = [c for c in found if c["kind"] == "history"]
    assert history and history[0]["price"] == "350000.0000"
    assert history[0]["reference"].startswith(rab["number"])
    assert history[0]["verified"] is False


def test_external_search_is_honestly_not_configured(tenant: Tenant) -> None:
    status = ok(tenant.browser.get("/api/v1/price-sources/external"))
    assert status["configured"] is False
    response = tenant.browser.post(
        "/api/v1/price-sources/external/search", params={"name": "semen"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "external_search_not_configured"


# --------------------------------------------------------------------------- RAB linkage


@pytest.fixture
def draft(db_session: Session, tenant: Tenant) -> str:
    project = make_project(db_session, tenant.org)
    rab = ok(tenant.browser.post(f"/api/v1/projects/{project.id}/rab", json={"title": "Baru"}), 201)
    return f"/api/v1/rab/{rab['id']}/versions/1"


def test_rab_item_takes_price_from_catalog_server_side(
    tenant: Tenant, approver: TestClient, draft: str
) -> None:
    item = make_item(tenant.browser, code="NET-01")
    observation = add_price(tenant.browser, item["id"], price="4500.75")

    version = ok(
        tenant.browser.post(
            f"{draft}/items",
            json={
                "name": "Kabel",
                "quantity": "10",
                "unit": "M",  # alias of "m"
                "unit_price": "1",  # ignored: the catalog price is authoritative
                "price_observation_id": observation["id"],
            },
        ),
        201,
    )

    line = version["items"][0]
    assert line["unit_price"] == "4500.7500"
    assert line["subtotal"] == "45007.50"
    assert line["price_source_type"] == "catalog"
    assert "NET-01" in line["price_source"] and "belum terverifikasi" in line["price_source"]
    assert line["price_verification_status"] == "unverified"
    assert any(i["code"] == "unverified_catalog_price" for i in version["issues"])

    ok(verify(approver, observation["id"]))
    refreshed = ok(tenant.browser.get(draft))
    assert refreshed["items"][0]["price_verification_status"] == "verified"
    assert not any(i["code"] == "unverified_catalog_price" for i in refreshed["issues"])


def test_rab_refuses_incompatible_or_rejected_catalog_prices(
    tenant: Tenant, approver: TestClient, other_tenant: Tenant, draft: str
) -> None:
    item = make_item(tenant.browser)
    observation = add_price(tenant.browser, item["id"])
    usd = add_price(tenant.browser, item["id"], currency="USD")
    rejected = add_price(tenant.browser, item["id"])
    ok(verify(approver, rejected["id"], "rejected", "Salah input"))
    foreign_item = make_item(other_tenant.browser)
    foreign = add_price(other_tenant.browser, foreign_item["id"])

    def post(observation_id: str, unit: str = "m") -> int:
        return tenant.browser.post(
            f"{draft}/items",
            json={
                "name": "X",
                "quantity": "1",
                "unit": unit,
                "price_observation_id": observation_id,
            },
        ).status_code

    assert post(observation["id"], unit="roll") == 422
    assert post(usd["id"]) == 422
    assert post(rejected["id"]) == 422
    assert post(foreign["id"]) == 404


# --------------------------------------------------------------------------- isolation


def test_catalog_is_isolated_between_organizations(tenant: Tenant, other_tenant: Tenant) -> None:
    mine = make_item(tenant.browser, name="Rahasia Alfa")
    observation = add_price(tenant.browser, mine["id"])
    b = other_tenant.browser

    assert b.get(f"/api/v1/price-catalog/{mine['id']}").status_code == 404
    assert (
        b.post(
            f"/api/v1/price-catalog/{mine['id']}/observations",
            json={"price": "1", "observed_at": TODAY},
        ).status_code
        == 404
    )
    assert (
        b.patch(
            f"/api/v1/price-catalog/{mine['id']}", json={"name": "x", "unit": "m", "version": 1}
        ).status_code
        == 404
    )
    assert b.get("/api/v1/price-catalog").json()["total"] == 0
    assert b.get("/api/v1/price-catalog/candidates", params={"name": "Rahasia Alfa"}).json() == []
    assert b.get("/api/v1/price-catalog/categories").json() == []
    owner_of_b = b.get("/api/v1/auth/me").json()
    assert owner_of_b["role"] == "owner"
    assert verify(b, observation["id"]).status_code == 404


def test_price_dates_are_validated(tenant: Tenant) -> None:
    item = make_item(tenant.browser)
    future_end = (date.today() + timedelta(days=30)).isoformat()
    ok_obs = add_price(tenant.browser, item["id"], valid_from=TODAY, valid_until=future_end)
    assert ok_obs["valid_until"] == future_end
    assert Decimal(ok_obs["price"]) == Decimal("4500")
