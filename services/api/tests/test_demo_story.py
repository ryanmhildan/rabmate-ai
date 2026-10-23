"""The demo story runs end to end through the public API and leaves a coherent business state."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.demo_seed import demo_email, seed_demo
from app.demo_story import build_demo_story
from app.modules.identity.permissions import Role
from tests.factories import login
from tests.test_rab_api import ok

PASSWORD = "sandi-demo-123"


def test_demo_story_builds_every_module_through_the_api(
    db_session: Session, settings: Settings, app: FastAPI
) -> None:
    seed_demo(db_session, password=PASSWORD, settings=settings)
    story = build_demo_story(app, password=PASSWORD)

    owner = TestClient(app)
    assert login(owner, demo_email(Role.OWNER), PASSWORD).status_code == 200

    # Catalog: sources and verification states are kept apart.
    semen = ok(owner.get("/api/v1/price-catalog", params={"q": "Semen"}))["items"][0]
    assert semen["prices"]["latest_verified"]["price"] == "65000.0000"
    assert semen["prices"]["latest_any"]["price"] == "67500.0000"
    assert semen["prices"]["latest_any"]["verification_status"] == "unverified"
    besi = ok(owner.get("/api/v1/price-catalog", params={"q": "Besi"}))["items"][0]
    assert besi["prices"]["latest_verified"] is None

    # RAB: approved v1 issued as a document; the v2 draft does not change it.
    rab = ok(owner.get(f"/api/v1/rab/{story.rab_id}"))
    assert [v["status"] for v in rab["versions"]] == ["approved", "draft"]
    v1 = ok(owner.get(f"/api/v1/rab/{story.rab_id}/versions/1"))
    v2 = ok(owner.get(f"/api/v1/rab/{story.rab_id}/versions/2"))
    assert len(v1["items"]) == 6 and len(v2["items"]) == 7
    assert {i["price_source_type"] for i in v1["items"]} == {"catalog", "manual"}
    # Only the unverified catalog price is flagged (a warning, not a blocker).
    assert [(i["severity"], i["code"]) for i in v1["issues"]] == [
        ("warning", "unverified_catalog_price")
    ]
    assert "Besi beton" in v1["issues"][0]["message"]
    document = ok(owner.get(f"/api/v1/documents/{story.rab_document_id}"))
    assert document["status"] == "issued"
    assert document["snapshot"]["totals"]["grand_total"] == v1["totals"]["grand_total"]
    assert Decimal(v2["totals"]["grand_total"]) > Decimal(v1["totals"]["grand_total"])

    # Quotation → SPK → BAST, all issued; the handover counts against the contract.
    quotation = ok(owner.get(f"/api/v1/quotations/{story.quotation_id}"))
    assert (quotation["status"], quotation["client_response"]) == ("issued", "accepted")
    assert [t["name"] for t in quotation["payment_terms"]] == ["Uang muka", "Termin 2", "Pelunasan"]
    spk = ok(owner.get(f"/api/v1/spk/{story.spk_id}"))
    assert spk["status"] == "issued" and spk["number"].startswith("SPK-")
    bast = ok(owner.get(f"/api/v1/bast/{story.bast_id}"))
    assert (bast["status"], bast["kind"], len(bast["items"])) == ("issued", "partial", 2)
    progress = ok(owner.get(f"/api/v1/spk/{story.spk_id}/progress"))["items"]
    semen_row = next(r for r in progress if r["name"] == "Semen Portland 50 kg")
    assert Decimal(semen_row["delivered_quantity"]) == Decimal(60)
    assert Decimal(semen_row["remaining_quantity"]) == Decimal(60)

    # Down-payment invoice paid in part, from a recorded payment.
    invoice = ok(owner.get(f"/api/v1/invoices/{story.invoice_id}"))
    assert invoice["status"] == "issued"
    paid, total = Decimal(invoice["amount_paid"]), Decimal(invoice["grand_total"])
    assert abs(paid * 2 - total) <= 1  # half, rounded to the rupiah
    assert Decimal(invoice["outstanding"]) == total - paid

    # One RAB waits for approval; one draft still lacks a price.
    queue = ok(owner.get("/api/v1/approvals/pending"))
    assert story.in_review_rab_id in {entry["rab_id"] for entry in queue}
    draft = ok(owner.get(f"/api/v1/rab/{story.draft_rab_id}/versions/1"))
    assert any(issue["code"] == "missing_price" for issue in draft["issues"])
