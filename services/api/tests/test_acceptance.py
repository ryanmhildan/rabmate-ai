"""MVP acceptance flow (master prompt §13), end to end through the HTTP API.

1. log in · 2. create a project (and its client) · 3. create a RAB · 4. add items ·
5. subtotal and grand total · 6. RAB versions · 7. PDF preview · 8. submit for approval ·
9. the approver approves · 10. the document is issued as a snapshot ·
11. later changes do not change the issued document.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.modules.identity.permissions import Role
from tests.factories import DEFAULT_PASSWORD, LoginAs, Tenant, login, make_user
from tests.test_rab_api import ok


def pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF-")
    return " ".join(
        " ".join(page.extract_text().split()) for page in PdfReader(io.BytesIO(content)).pages
    )


def test_mvp_acceptance_flow(
    db_session: Session,
    tenant: Tenant,
    login_as: LoginAs,
    client_factory: Any,
) -> None:
    # 1. Log in: a wrong password is refused; the right one opens a session.
    estimator_user = make_user(db_session, tenant.org, Role.ESTIMATOR)
    estimator: TestClient = client_factory()
    assert login(estimator, estimator_user.email, "salah-sandi-123").status_code == 401
    assert login(estimator, estimator_user.email, DEFAULT_PASSWORD).status_code == 200
    assert ok(estimator.get("/api/v1/auth/me"))["user"]["email"] == estimator_user.email
    pm = login_as(make_user(db_session, tenant.org, Role.PROJECT_MANAGER))
    approver = login_as(make_user(db_session, tenant.org, Role.APPROVER))
    finance = login_as(make_user(db_session, tenant.org, Role.FINANCE))

    # 2. A client and a project with PPN 11%.
    client = ok(
        pm.post(
            "/api/v1/clients", json={"code": "KLN-01", "name": "PT Klien Uji", "city": "Bogor"}
        ),
        201,
    )
    project = ok(
        pm.post(
            "/api/v1/projects",
            json={
                "name": "Gudang Logistik",
                "project_type": "construction",
                "client_id": client["id"],
                "currency": "IDR",
                "tax_label": "PPN",
                "tax_rate_percent": "11",
            },
        ),
        201,
    )

    # 3. A RAB for the project starts as draft version 1.
    rab = ok(
        estimator.post(f"/api/v1/projects/{project['id']}/rab", json={"title": "RAB Gudang"}), 201
    )
    v1 = f"/api/v1/rab/{rab['id']}/versions/1"
    assert ok(estimator.get(v1))["status"] == "draft"

    # 4. Items with decimal volumes and sourced prices.
    for item in (
        {"name": "Semen 50 kg", "quantity": "120", "unit": "sak", "unit_price": "65000"},
        {"name": "Pasir beton", "quantity": "18.5", "unit": "m3", "unit_price": "350000"},
        {
            "name": "Tukang batu",
            "item_type": "labor",
            "quantity": "60",
            "unit": "OH",
            "unit_price": "150000",
        },
    ):
        ok(
            estimator.post(
                f"{v1}/items",
                json={**item, "price_source_type": "manual", "price_source": "Survei 2026"},
            ),
            201,
        )

    # 5. Totals computed by the engine: 7.800.000 + 6.475.000 + 9.000.000 = 23.275.000;
    #    PPN 11% = 2.560.250; grand total 25.835.250.
    version = ok(estimator.get(v1))
    assert [i["subtotal"] for i in version["items"]] == ["7800000.00", "6475000.00", "9000000.00"]
    assert version["totals"]["subtotal"] == "23275000.00"
    assert version["totals"]["tax_amount"] == "2560250.00"
    assert version["totals"]["grand_total"] == "25835250.00"

    # 7. Preview PDF from the live data, marked as a preview.
    preview = estimator.get(f"{v1}/preview.pdf")
    assert preview.status_code == 200
    text = pdf_text(preview.content)
    assert rab["number"] in text and "25.835.250" in text and "PRATINJAU" in text

    # 8. Submit for approval: the draft is locked.
    ok(estimator.post(f"{v1}/transitions/submit", json={"note": "Mohon ditinjau."}))
    locked = estimator.post(f"{v1}/items", json={"name": "X", "quantity": "1", "unit": "ls"})
    assert locked.status_code == 409

    # 9. Only an approver may approve.
    assert estimator.post(f"{v1}/transitions/approve", json={}).status_code == 403
    ok(approver.post(f"{v1}/transitions/approve", json={"note": "Sesuai anggaran."}))
    assert ok(approver.get(v1))["status"] == "approved"

    # 10. Issued as a document: frozen snapshot + stored files; retries return the same one.
    key = {"Idempotency-Key": "acceptance-issue-1"}
    document = ok(finance.post(f"{v1}/documents", headers=key), 201)
    assert ok(finance.post(f"{v1}/documents", headers=key), 200)["id"] == document["id"]
    detail = ok(finance.get(f"/api/v1/documents/{document['id']}"))
    assert detail["status"] == "issued"
    assert detail["snapshot"]["totals"]["grand_total"] == "25835250.00"
    issued_pdf = finance.get(f"/api/v1/documents/{document['id']}/files/pdf").content
    issued_text = pdf_text(issued_pdf)
    assert "25.835.250" in issued_text and "PRATINJAU" not in issued_text
    issued_hash = hashlib.sha256(issued_pdf).hexdigest()

    # 6 + 11. A new version is a separate draft; editing it leaves the issued document intact.
    v2_data = ok(estimator.post(f"/api/v1/rab/{rab['id']}/versions", json={}), 201)
    assert v2_data["version_no"] == 2
    v2 = f"/api/v1/rab/{rab['id']}/versions/2"
    ok(
        estimator.post(
            f"{v2}/items",
            json={
                "name": "Atap baja ringan",
                "quantity": "200",
                "unit": "m2",
                "unit_price": "185000",
                "price_source_type": "manual",
                "price_source": "Survei 2026",
            },
        ),
        201,
    )
    assert ok(estimator.get(v2))["totals"]["grand_total"] != "25835250.00"
    assert ok(estimator.get(v1))["status"] == "approved"
    after = ok(finance.get(f"/api/v1/documents/{document['id']}"))
    assert after["snapshot"] == detail["snapshot"]
    again = finance.get(f"/api/v1/documents/{document['id']}/files/pdf").content
    assert hashlib.sha256(again).hexdigest() == issued_hash
