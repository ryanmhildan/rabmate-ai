"""Quotations, payment terms, invoices and payments through the API."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.billing.models import Invoice
from app.modules.identity.permissions import Role
from tests.factories import LoginAs, Tenant, make_client, make_project, make_user
from tests.test_rab_api import Rab, ok

D = Decimal
TODAY = datetime.now(ZoneInfo("Asia/Jakarta")).date()
YEAR = TODAY.year
THIRTY_FORTY_THIRTY = [
    {
        "name": "Uang muka",
        "basis": "percent",
        "value": "30",
        "due_date": str(TODAY + timedelta(days=7)),
    },
    {"name": "Termin 2", "basis": "percent", "value": "40", "description": "Progres 70%"},
    {"name": "Pelunasan", "basis": "percent", "value": "30", "description": "Setelah BAST"},
]


def pdf_text(content: bytes) -> str:
    return " ".join(
        " ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(content)).pages
    )


class Roles:
    def __init__(self, db: Session, tenant: Tenant, login_as: LoginAs) -> None:
        self.owner = tenant.browser
        self.estimator = login_as(make_user(db, tenant.org, Role.ESTIMATOR))
        self.finance = login_as(make_user(db, tenant.org, Role.FINANCE))
        self.approver = login_as(make_user(db, tenant.org, Role.APPROVER))
        self.viewer = login_as(make_user(db, tenant.org, Role.VIEWER))


@pytest.fixture
def roles(db_session: Session, tenant: Tenant, login_as: LoginAs) -> Roles:
    return Roles(db_session, tenant, login_as)


@pytest.fixture
def client_id(db_session: Session, tenant: Tenant) -> str:
    return str(make_client(db_session, tenant.org, name="CV Klien Makmur").id)


@pytest.fixture
def rab(db_session: Session, tenant: Tenant, client_id: str) -> Rab:
    return network_rab(db_session, tenant, client_id)


def network_rab(db_session: Session, tenant: Tenant, client_id: str) -> Rab:
    """Draft RAB (approved by approve_rab): 9.711.500 + PPN 11% (1.068.265) = 10.779.765."""
    project = make_project(
        db_session,
        tenant.org,
        client_id=client_id,
        tax_label="PPN",
        tax_rate_percent=D("11"),
        currency="IDR",
    )
    created = ok(
        tenant.browser.post(f"/api/v1/projects/{project.id}/rab", json={"title": "RAB Jaringan"}),
        201,
    )
    rab = Rab(tenant.browser, created)
    ok(rab.add(name="Kabel UTP", quantity="305", unit="m", unit_price="4300"), 201)
    ok(
        rab.add(
            name="Instalasi", item_type="service", quantity="48", unit="titik", unit_price="175000"
        ),
        201,
    )
    return rab


def approve_rab(rab: Rab) -> str:
    ok(rab.act("submit"))
    return str(ok(rab.act("approve", note="OK"))["id"])


def act(browser: TestClient, kind: str, entity: dict[str, Any], action: str, **body: Any) -> Any:
    return browser.post(f"/api/v1/{kind}/{entity['id']}/transitions/{action}", json=body)


def issued_quotation(roles: Roles, rab: Rab, *, accept: bool = True) -> dict[str, Any]:
    quotation = ok(
        roles.estimator.post("/api/v1/quotations", json={"rab_version_id": approve_rab(rab)}), 201
    )
    quotation = ok(
        roles.estimator.put(
            f"/api/v1/quotations/{quotation['id']}/terms",
            json={"version": quotation["version"], "terms": THIRTY_FORTY_THIRTY},
        )
    )
    ok(act(roles.estimator, "quotations", quotation, "submit"))
    ok(act(roles.approver, "quotations", quotation, "approve"))
    ok(
        roles.finance.post(
            f"/api/v1/quotations/{quotation['id']}/issue",
            headers={"Idempotency-Key": f"q-{quotation['id']}"},
        ),
        201,
    )
    if accept:
        ok(
            roles.estimator.post(
                f"/api/v1/quotations/{quotation['id']}/response", json={"response": "accepted"}
            )
        )
    result: dict[str, Any] = ok(roles.owner.get(f"/api/v1/quotations/{quotation['id']}"))
    return result


def issued_term_invoice(roles: Roles, quotation: dict[str, Any], index: int = 0) -> dict[str, Any]:
    term = quotation["payment_terms"][index]
    invoice = ok(
        roles.finance.post(f"/api/v1/quotations/{quotation['id']}/terms/{term['id']}/invoice"), 201
    )
    return issue_draft(roles, invoice)


def issue_draft(roles: Roles, invoice: dict[str, Any]) -> dict[str, Any]:
    if invoice["due_date"] is None:
        invoice = ok(
            roles.finance.patch(
                f"/api/v1/invoices/{invoice['id']}",
                json={
                    "version": invoice["version"],
                    "title": invoice["title"],
                    "due_date": str(TODAY + timedelta(days=14)),
                    "tax_label": invoice["tax_label"],
                    "tax_rate_percent": invoice["tax_rate_percent"],
                },
            )
        )
    ok(act(roles.finance, "invoices", invoice, "submit"))
    ok(act(roles.approver, "invoices", invoice, "approve"))
    ok(
        roles.finance.post(
            f"/api/v1/invoices/{invoice['id']}/issue",
            headers={"Idempotency-Key": f"i-{invoice['id']}"},
        ),
        201,
    )
    result: dict[str, Any] = ok(roles.finance.get(f"/api/v1/invoices/{invoice['id']}"))
    return result


def pay(
    browser: TestClient,
    client_id: str,
    invoice: dict[str, Any] | None,
    amount: str,
    *,
    allocate: str | None = None,
    key: str | None = None,
    **extra: Any,
) -> Any:
    body = {
        "client_id": client_id,
        "payment_date": str(TODAY),
        "amount": amount,
        "method": "transfer",
        "reference": "TRF-001",
        "allocations": [{"invoice_id": invoice["id"], "amount": allocate or amount}]
        if invoice
        else [],
        **extra,
    }
    return browser.post(
        "/api/v1/payments", json=body, headers={"Idempotency-Key": key} if key else {}
    )


# --------------------------------------------------------------------------- quotations


def test_quotation_from_approved_rab_with_thirty_forty_thirty(
    roles: Roles, rab: Rab, db_session: Session
) -> None:
    draft_version = rab.version()["id"]
    assert (
        roles.estimator.post(
            "/api/v1/quotations", json={"rab_version_id": draft_version}
        ).status_code
        == 409
    )
    quotation = ok(
        roles.estimator.post("/api/v1/quotations", json={"rab_version_id": approve_rab(rab)}), 201
    )
    assert quotation["number"] == f"PNW-{YEAR}-0001"
    assert quotation["status"] == "draft"
    assert (quotation["taxable_base"], quotation["tax_amount"], quotation["grand_total"]) == (
        "9711500.00",
        "1068265.00",
        "10779765.00",
    )
    assert quotation["valid_until"] == str(TODAY + timedelta(days=30))
    assert quotation["editable"] is True
    # A schedule is required before review.
    assert act(roles.estimator, "quotations", quotation, "submit").status_code == 422

    url = f"/api/v1/quotations/{quotation['id']}/terms"
    bad = roles.estimator.put(
        url, json={"version": quotation["version"], "terms": THIRTY_FORTY_THIRTY[:2]}
    )
    assert bad.status_code == 422
    assert "saat ini 70%" in bad.json()["error"]["message"]
    quotation = ok(
        roles.estimator.put(
            url, json={"version": quotation["version"], "terms": THIRTY_FORTY_THIRTY}
        )
    )
    terms = quotation["payment_terms"]
    assert [t["amount"] for t in terms] == ["2913450.00", "3884600.00", "2913450.00"]
    assert [t["tax_amount"] for t in terms] == ["320479.50", "427306.00", "320479.50"]
    assert [t["total_amount"] for t in terms] == ["3233929.50", "4311906.00", "3233929.50"]
    assert sum(D(t["total_amount"]) for t in terms) == D(quotation["grand_total"])
    stale = roles.estimator.put(
        url, json={"version": quotation["version"] - 1, "terms": THIRTY_FORTY_THIRTY}
    )
    assert stale.status_code == 409

    # Mixed fixed amount + percent must match exactly.
    mixed = roles.estimator.put(
        url,
        json={
            "version": quotation["version"],
            "terms": [
                {"name": "DP", "basis": "amount", "value": "1000000"},
                {"name": "Sisa", "basis": "percent", "value": "80"},
            ],
        },
    )
    assert mixed.status_code == 422 and "kurang" in mixed.json()["error"]["message"]

    # Review: authors submit, only approvers approve.
    ok(act(roles.estimator, "quotations", quotation, "submit"))
    assert act(roles.estimator, "quotations", quotation, "approve").status_code == 403
    assert (
        act(roles.approver, "quotations", quotation, "reject").status_code == 422
    )  # note required
    ok(act(roles.approver, "quotations", quotation, "reject", note="Revisi uang muka"))
    ok(act(roles.estimator, "quotations", quotation, "reopen"))
    ok(act(roles.estimator, "quotations", quotation, "submit"))
    approved = ok(act(roles.approver, "quotations", quotation, "approve"))
    assert [a["action"] for a in approved["approvals"]] == [
        "submitted",
        "rejected",
        "reopened",
        "submitted",
        "approved",
    ]

    # Issue: idempotent, PDF with the schedule.
    issue_url = f"/api/v1/quotations/{quotation['id']}/issue"
    assert (
        roles.estimator.post(issue_url, headers={"Idempotency-Key": "quote-key-1"}).status_code
        == 403
    )
    document = ok(roles.finance.post(issue_url, headers={"Idempotency-Key": "quote-key-1"}), 201)
    assert document["doc_type"] == "quotation" and document["number"] == quotation["number"]
    replay = roles.finance.post(issue_url, headers={"Idempotency-Key": "quote-key-1"})
    assert replay.status_code == 200 and replay.json()["id"] == document["id"]
    assert (
        roles.finance.post(issue_url, headers={"Idempotency-Key": "quote-key-2"}).status_code == 409
    )
    text = pdf_text(roles.owner.get(f"/api/v1/documents/{document['id']}/files/pdf").content)
    for expected in (
        "SURAT PENAWARAN HARGA",
        quotation["number"],
        "Jadwal pembayaran",
        "Rp 3.233.929,50",
        "Rp 4.311.906",
        "Total Rp 10.779.765",
    ):
        assert expected in text, expected
    listed = ok(roles.owner.get(f"/api/v1/documents?quotation_id={quotation['id']}"))
    assert [d["id"] for d in listed["items"]] == [document["id"]]

    detail = ok(roles.owner.get(f"/api/v1/quotations/{quotation['id']}"))
    assert detail["status"] == "issued" and detail["editable"] is False
    assert detail["can_invoice"] is False  # not accepted yet
    # Quotation documents are voided via the quotation, not the generic endpoint.
    assert (
        roles.owner.post(
            f"/api/v1/documents/{document['id']}/void", json={"reason": "x"}
        ).status_code
        == 409
    )


def test_preview_and_permissions(roles: Roles, rab: Rab) -> None:
    quotation = ok(
        roles.estimator.post("/api/v1/quotations", json={"rab_version_id": approve_rab(rab)}), 201
    )
    preview = roles.viewer.get(f"/api/v1/quotations/{quotation['id']}/preview.pdf")
    assert preview.status_code == 200
    assert "PRATINJAU" in pdf_text(preview.content)
    assert (
        roles.viewer.patch(
            f"/api/v1/quotations/{quotation['id']}", json={"version": 1, "subject": "x"}
        ).status_code
        == 403
    )
    assert roles.viewer.get("/api/v1/invoices").status_code == 403  # no finance.read
    assert roles.estimator.get("/api/v1/payments").status_code == 403


def test_term_invoices_partial_payments_and_balance(
    roles: Roles, rab: Rab, client_id: str, db_session: Session
) -> None:
    quotation = issued_quotation(roles, rab, accept=False)
    term = quotation["payment_terms"][0]
    term_url = f"/api/v1/quotations/{quotation['id']}/terms/{term['id']}/invoice"
    assert roles.finance.post(term_url).status_code == 409  # client has not accepted yet
    ok(
        roles.estimator.post(
            f"/api/v1/quotations/{quotation['id']}/response", json={"response": "accepted"}
        )
    )

    draft = ok(roles.finance.post(term_url), 201)
    assert draft["kind"] == "term" and draft["number"] is None
    assert (draft["subtotal"], draft["tax_amount"], draft["grand_total"]) == (
        "2913450.00",
        "320479.50",
        "3233929.50",
    )
    assert draft["due_date"] == str(TODAY + timedelta(days=7))  # from the term
    assert roles.finance.post(term_url).status_code == 409  # one invoice per term
    # Term invoices keep the schedule's figures.
    locked = roles.finance.patch(
        f"/api/v1/invoices/{draft['id']}",
        json={
            "version": draft["version"],
            "title": draft["title"],
            "items": [{"description": "x", "quantity": "1", "unit": "ls", "unit_price": "1"}],
        },
    )
    assert locked.status_code == 422

    invoice = issue_draft(roles, draft)
    assert invoice["number"] == f"INV-{YEAR}-0001"
    assert invoice["issue_date"] == str(TODAY)
    assert invoice["payment_state"] == "unpaid" and invoice["outstanding"] == "3233929.50"
    assert invoice["can_record_payment"] is True

    first = ok(pay(roles.finance, client_id, invoice, "1000000"), 201)
    assert first["allocated"] == "1000000.00" and first["unallocated"] == "0.00"
    invoice = ok(roles.finance.get(f"/api/v1/invoices/{invoice['id']}"))
    assert (invoice["payment_state"], invoice["amount_paid"], invoice["outstanding"]) == (
        "partial",
        "1000000.00",
        "2233929.50",
    )

    over = pay(roles.finance, client_id, invoice, "3000000")
    assert over.status_code == 422 and "sisa tagihan" in over.json()["error"]["message"]
    second = ok(pay(roles.finance, client_id, invoice, "2233929.50", key="pay-key-0002"), 201)
    invoice = ok(roles.finance.get(f"/api/v1/invoices/{invoice['id']}"))
    assert (invoice["payment_state"], invoice["outstanding"]) == ("paid", "0.00")
    assert invoice["can_record_payment"] is False
    assert [a["amount"] for a in invoice["allocations"]] == ["1000000.00", "2233929.50"]

    # Retried request with the same key: same payment, nothing booked twice.
    replay = pay(roles.finance, client_id, invoice, "2233929.50", key="pay-key-0002")
    assert replay.status_code == 200 and replay.json()["id"] == second["id"]
    assert pay(roles.finance, client_id, invoice, "5", key="pay-key-0002").status_code == 422

    # A paid invoice cannot be voided; voiding a payment reopens the balance.
    assert (
        roles.finance.post(
            f"/api/v1/invoices/{invoice['id']}/void", json={"reason": "x"}
        ).status_code
        == 409
    )
    voided = ok(
        roles.finance.post(f"/api/v1/payments/{first['id']}/void", json={"reason": "Salah input"})
    )
    assert voided["status"] == "void"
    assert (
        roles.finance.post(
            f"/api/v1/payments/{first['id']}/void", json={"reason": "lagi"}
        ).status_code
        == 409
    )
    invoice = ok(roles.finance.get(f"/api/v1/invoices/{invoice['id']}"))
    assert (invoice["payment_state"], invoice["outstanding"]) == ("partial", "1000000.00")
    assert [a["payment_status"] for a in invoice["allocations"]] == ["void", "recorded"]

    # All three terms billed: the invoices add up to the quotation exactly.
    others = [issued_term_invoice(roles, quotation, i) for i in (1, 2)]
    assert sum(D(i["grand_total"]) for i in [invoice, *others]) == D(quotation["grand_total"])
    assert [i["number"] for i in others] == [f"INV-{YEAR}-0002", f"INV-{YEAR}-0003"]
    detail = ok(roles.owner.get(f"/api/v1/quotations/{quotation['id']}"))
    assert all(t["invoice"] for t in detail["payment_terms"])
    assert detail["can_void"] is False  # invoices depend on it

    actions = set(
        db_session.execute(
            select(AuditLog.action).where(AuditLog.entity_type.in_(["invoice", "payment"]))
        ).scalars()
    )
    assert {
        "invoice.create",
        "invoice.submit",
        "invoice.approve",
        "payment.record",
        "payment.void",
    } <= actions


def test_manual_invoice_lines_tax_and_review_rules(
    roles: Roles, db_session: Session, tenant: Tenant, client_id: str
) -> None:
    no_client = make_project(db_session, tenant.org)
    assert (
        roles.finance.post(
            "/api/v1/invoices", json={"project_id": str(no_client.id), "title": "X"}
        ).status_code
        == 422
    )
    project = make_project(
        db_session, tenant.org, client_id=client_id, tax_label="PPN", tax_rate_percent=D("11")
    )
    invoice = ok(
        roles.finance.post(
            "/api/v1/invoices", json={"project_id": str(project.id), "title": "Jasa konsultasi"}
        ),
        201,
    )
    assert (invoice["kind"], invoice["tax_label"], invoice["grand_total"]) == (
        "manual",
        "PPN",
        "0.00",
    )
    assert (
        act(roles.finance, "invoices", invoice, "submit").status_code == 422
    )  # no lines, no due date

    url = f"/api/v1/invoices/{invoice['id']}"
    body = {
        "version": invoice["version"],
        "title": "Jasa konsultasi Oktober",
        "due_date": str(TODAY - timedelta(days=1)),
        "tax_label": "PPN",
        "tax_rate_percent": "11",
        "items": [
            {"description": "Konsultasi", "quantity": "1", "unit": "ls", "unit_price": "1000000"},
            {
                "description": "Perjalanan",
                "quantity": "3",
                "unit": "kali",
                "unit_price": "250000.50",
            },
        ],
    }
    invoice = ok(roles.finance.patch(url, json=body))
    assert (invoice["subtotal"], invoice["tax_amount"], invoice["grand_total"]) == (
        "1750001.50",
        "192500.17",
        "1942501.67",
    )
    assert [i["amount"] for i in invoice["items"]] == ["1000000.00", "750001.50"]
    refused = act(roles.finance, "invoices", invoice, "submit")
    assert (
        refused.status_code == 422
        and "jatuh tempo sudah lewat" in refused.json()["error"]["message"]
    )
    invoice = ok(
        roles.finance.patch(
            url, json={**body, "version": invoice["version"], "due_date": str(TODAY)}
        )
    )
    assert (
        roles.finance.patch(url, json={**body, "version": invoice["version"] - 1}).status_code
        == 409
    )
    assert (
        roles.finance.patch(
            url, json={**body, "version": invoice["version"], "tax_rate_percent": None}
        ).status_code
        == 422
    )

    ok(act(roles.finance, "invoices", invoice, "submit"))
    assert (
        roles.finance.patch(url, json={**body, "version": invoice["version"] + 1}).status_code
        == 409
    )  # locked
    ok(act(roles.approver, "invoices", invoice, "approve"))
    ok(act(roles.finance, "invoices", invoice, "reopen"))  # back to draft before issuing is allowed
    ok(act(roles.finance, "invoices", invoice, "submit"))
    ok(act(roles.approver, "invoices", invoice, "approve"))
    document = ok(roles.finance.post(f"{url}/issue"), 201)
    text = pdf_text(roles.finance.get(f"/api/v1/documents/{document['id']}/files/pdf").content)
    for expected in (
        "INVOICE",
        document["number"],
        "Konsultasi",
        "Rp 250.000,50",
        "Total tagihan Rp 1.942.501,67",
    ):
        assert expected in text, expected
    assert roles.finance.delete(url).status_code == 409  # issued invoices are voided, not deleted

    # Draft invoices can be deleted outright.
    other = ok(
        roles.finance.post(
            "/api/v1/invoices", json={"project_id": str(project.id), "title": "Sementara"}
        ),
        201,
    )
    assert roles.finance.delete(f"/api/v1/invoices/{other['id']}").status_code == 204


def test_overdue_and_dashboard(roles: Roles, rab: Rab, client_id: str, db_session: Session) -> None:
    quotation = issued_quotation(roles, rab)
    invoice = issued_term_invoice(roles, quotation)
    assert invoice["overdue"] is False
    db_session.execute(
        update(Invoice)
        .where(Invoice.id == invoice["id"])
        .values(issue_date=TODAY - timedelta(days=20), due_date=TODAY - timedelta(days=6))
    )
    db_session.commit()
    invoice = ok(roles.finance.get(f"/api/v1/invoices/{invoice['id']}"))
    assert invoice["overdue"] is True
    assert ok(roles.finance.get("/api/v1/invoices?overdue=true"))["total"] == 1
    assert ok(roles.finance.get("/api/v1/invoices?payment_state=unpaid"))["total"] == 1
    ok(pay(roles.finance, client_id, invoice, "500000"), 201)
    summary = ok(roles.owner.get("/api/v1/dashboard/summary"))
    billing = summary["billing"]
    assert billing["outstanding"] == [{"currency": "IDR", "total": "2733929.50", "count": 1}]
    assert billing["overdue"] == [{"currency": "IDR", "total": "2733929.50", "count": 1}]
    assert billing["received_this_month"] == [{"currency": "IDR", "total": "500000.00", "count": 1}]
    assert billing["terms_due_soon"] == 0  # only the first term has a due date, and it is billed
    assert summary["quotations"] == {
        "draft": 0,
        "in_review": 0,
        "awaiting_response": 0,
        "accepted": 1,
    }
    assert ok(roles.estimator.get("/api/v1/dashboard/summary"))["billing"] is None


def test_payment_rules(
    roles: Roles, rab: Rab, client_id: str, db_session: Session, tenant: Tenant
) -> None:
    quotation = issued_quotation(roles, rab)
    draft = ok(
        roles.finance.post(
            f"/api/v1/quotations/{quotation['id']}/terms/{quotation['payment_terms'][1]['id']}/invoice"
        ),
        201,
    )
    assert pay(roles.finance, client_id, draft, "1000").status_code == 422  # not issued
    invoice = issued_term_invoice(roles, quotation)
    other_client = str(make_client(db_session, tenant.org, name="Lain").id)
    assert pay(roles.finance, other_client, invoice, "1000").status_code == 422
    assert (
        pay(
            roles.finance, client_id, invoice, "1000", payment_date=str(TODAY + timedelta(days=1))
        ).status_code
        == 422
    )
    assert (
        pay(roles.finance, client_id, invoice, "1000", allocate="2000").status_code == 422
    )  # > payment
    assert pay(roles.estimator, client_id, invoice, "1000").status_code == 403

    # Money received before deciding where it goes stays unallocated until allocated.
    payment = ok(pay(roles.finance, client_id, None, "1500000"), 201)
    assert payment["unallocated"] == "1500000.00"
    payment = ok(
        roles.finance.post(
            f"/api/v1/payments/{payment['id']}/allocations",
            json={"invoice_id": invoice["id"], "amount": "1500000"},
        )
    )
    assert payment["unallocated"] == "0.00"
    assert (
        roles.finance.post(
            f"/api/v1/payments/{payment['id']}/allocations",
            json={"invoice_id": invoice["id"], "amount": "1"},
        ).status_code
        == 422
    )
    assert ok(roles.finance.get(f"/api/v1/payments?invoice_id={invoice['id']}"))["total"] == 1


def test_quotation_void_delete_and_isolation(
    roles: Roles, rab: Rab, other_tenant: Tenant, client_id: str
) -> None:
    quotation = issued_quotation(roles, rab, accept=False)
    url = f"/api/v1/quotations/{quotation['id']}"
    assert roles.estimator.delete(url).status_code == 409
    assert roles.estimator.post(f"{url}/void", json={"reason": "x"}).status_code == 403
    voided = ok(roles.finance.post(f"{url}/void", json={"reason": "Klien membatalkan"}))
    assert voided["status"] == "void"
    docs = ok(roles.owner.get(f"/api/v1/documents?quotation_id={quotation['id']}"))["items"]
    assert [d["status"] for d in docs] == ["void"]

    draft = ok(
        roles.estimator.post(
            "/api/v1/quotations",
            json={"rab_version_id": quotation_version(roles, rab)},
        ),
        201,
    )
    assert roles.estimator.delete(f"/api/v1/quotations/{draft['id']}").status_code == 204

    stranger = other_tenant.browser
    assert stranger.get(url).status_code == 404
    assert stranger.get(f"{url}/preview.pdf").status_code == 404
    assert ok(stranger.get("/api/v1/quotations"))["total"] == 0
    assert (
        stranger.post(
            "/api/v1/payments",
            json={
                "client_id": client_id,
                "payment_date": str(TODAY),
                "amount": "1",
                "method": "cash",
            },
        ).status_code
        == 404
    )


def quotation_version(roles: Roles, rab: Rab) -> str:
    return str(rab.version()["id"])
