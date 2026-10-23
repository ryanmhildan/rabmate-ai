"""The demo business story, built through the public API in-process (ADR-045).

`seed_demo` creates the demo organization, users, clients and projects. This module then plays
the story the way the demo users would in the browser — each step logged in as the role that does
it in real life — so permissions, CSRF, validation, numbering, totals, snapshots, idempotency and
audit apply to demo data exactly as to real data. Nothing is written to tables directly.

All names carry "(Demo)"; people are fictional placeholders. No tax numbers, bank accounts or
signatures are invented: those fields stay empty, as a real user would have to fill them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.demo_seed import DemoSeedError, demo_email
from app.modules.identity.permissions import Role

API = "/api/v1"
CSRF_COOKIE = "rabmate_csrf"
SUPPLIER = "Toko Bangunan Sumber Rejeki (Demo)"


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Jakarta")).date()


class _Actor:
    """One demo user's browser: own cookie jar, CSRF header, readable errors."""

    def __init__(self, app: FastAPI, role: Role, password: str) -> None:
        self.role = role
        self.client = TestClient(app, base_url="http://localhost")
        response = self.client.post(
            f"{API}/auth/login", json={"email": demo_email(role), "password": password}
        )
        if response.status_code != 200:
            raise DemoSeedError(f"Login demo {role.value} gagal ({response.status_code}).")
        self.client.headers["X-CSRF-Token"] = self.client.cookies[CSRF_COOKIE]

    def call(
        self,
        method: str,
        path: str,
        expect: int = 200,
        *,
        json: Any = None,
        idempotent: bool = False,
    ) -> Any:
        headers = {"Idempotency-Key": f"demo-{uuid.uuid4().hex}"} if idempotent else None
        response = self.client.request(method, f"{API}{path}", json=json, headers=headers)
        if response.status_code != expect:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.text[:200]
            raise DemoSeedError(
                f"Langkah demo gagal ({self.role.value}: {method} {path} → "
                f"{response.status_code}): {message}"
            )
        return response.json() if response.content else None

    def close(self) -> None:
        self.client.close()


@dataclass
class DemoStory:
    """Ids of what the story created, for the CLI summary and tests."""

    catalog: dict[str, str] = field(default_factory=dict)
    rab_id: str = ""
    rab_number: str = ""
    rab_document_id: str = ""
    quotation_id: str = ""
    spk_id: str = ""
    bast_id: str = ""
    invoice_id: str = ""
    payment_id: str = ""
    in_review_rab_id: str = ""
    draft_rab_id: str = ""


def _projects(actor: _Actor) -> dict[str, dict[str, Any]]:
    page = actor.call("GET", "/projects?page_size=100")
    return {p["name"]: p for p in page["items"]}


def _catalog(estimator: _Actor, approver: _Actor, today: date) -> dict[str, str]:
    """Sourced prices: verified, unverified, and one superseded by a newer unverified quote."""
    supplier = estimator.call("POST", "/suppliers", 201, json={"name": SUPPLIER, "city": "Bandung"})
    quote = f"Penawaran SR/{today:%m}/{today:%Y} (Demo)"
    specs: list[tuple[dict[str, Any], list[tuple[str, int, bool]]]] = [
        (
            {
                "code": "MAT-SMN-50",
                "name": "Semen Portland 50 kg",
                "unit": "sak",
                "category": "Material",
            },
            [("65000", 30, True), ("67500", 3, False)],
        ),
        (
            {"code": "MAT-PSR-BTN", "name": "Pasir beton", "unit": "m3", "category": "Material"},
            [("350000", 20, True)],
        ),
        (
            {
                "code": "MAT-BSI-10",
                "name": "Besi beton polos 10 mm",
                "unit": "batang",
                "category": "Material",
            },
            [("78000", 5, False)],
        ),
        (
            {
                "code": "MAT-CAT-5",
                "name": "Cat tembok interior 5 kg",
                "unit": "pail",
                "category": "Finishing",
                "brand": "Merek Contoh (Demo)",
            },
            [("185000", 12, True)],
        ),
        (
            {
                "code": "UPH-TKG-BT",
                "name": "Upah tukang batu",
                "unit": "OH",
                "category": "Tenaga kerja",
                "item_type": "labor",
            },
            [("150000", 40, True)],
        ),
    ]
    observations: dict[str, str] = {}
    for body, prices in specs:
        item = estimator.call("POST", "/price-catalog", 201, json=body)
        labor = body.get("item_type") == "labor"
        source = (
            {"source_type": "manual", "source_reference": "Standar upah internal (Demo)"}
            if labor
            else {
                "source_type": "vendor_quote",
                "source_reference": quote,
                "supplier_id": supplier["id"],
            }
        )
        for price, days_ago, verified in prices:
            observation = estimator.call(
                "POST",
                f"/price-catalog/{item['id']}/observations",
                201,
                json={
                    "price": price,
                    "observed_at": str(today - timedelta(days=days_ago)),
                    **source,
                },
            )
            if verified:
                approver.call(
                    "POST",
                    f"/price-observations/{observation['id']}/verification",
                    json={"status": "verified", "note": "Dicek dengan dokumen penawaran (Demo)."},
                )
            # The RAB uses the verified price when there is one, like an estimator would.
            if verified or body["name"] not in observations:
                observations[body["name"]] = observation["id"]
    return observations


def build_demo_story(app: FastAPI, *, password: str) -> DemoStory:
    """Plays the demo story; requires the demo organization from `seed_demo`."""
    actors = {role: _Actor(app, role, password) for role in Role}
    try:
        return _play(actors, _today())
    finally:
        for actor in actors.values():
            actor.close()


def _play(actors: dict[Role, _Actor], today: date) -> DemoStory:
    owner = actors[Role.OWNER]
    pm = actors[Role.PROJECT_MANAGER]
    estimator = actors[Role.ESTIMATOR]
    finance = actors[Role.FINANCE]
    approver = actors[Role.APPROVER]
    story = DemoStory()

    settings = owner.call("GET", "/document-settings")
    owner.call(
        "PUT",
        "/document-settings",
        json={
            **{k: v for k, v in settings.items() if k not in ("version", "updated_at")},
            "version": settings["version"],
            "tagline": "Kontraktor umum & pengadaan (Demo)",
            "footer_text": "Dokumen contoh dari data demo RABmate — bukan dokumen sah.",
            "show_price_sources": True,
        },
    )

    # 1. Price catalog with sources and verification states.
    story.catalog = _catalog(estimator, approver, today)

    # 2. RAB from catalog prices and one manual estimate; approved and issued as a document.
    projects = _projects(estimator)
    archive = projects["Renovasi Gedung Arsip (Demo)"]
    rab = estimator.call(
        "POST",
        f"/projects/{archive['id']}/rab",
        201,
        json={"title": "RAB Renovasi Ruang Arsip Lt. 1 (Demo)"},
    )
    story.rab_id, story.rab_number = rab["id"], rab["number"]
    v1 = f"/rab/{rab['id']}/versions/1"
    lines = [
        ("Semen Portland 50 kg", "120", "sak", "material", "Pekerjaan struktur"),
        ("Pasir beton", "18", "m3", "material", "Pekerjaan struktur"),
        ("Besi beton polos 10 mm", "240", "batang", "material", "Pekerjaan struktur"),
        ("Cat tembok interior 5 kg", "36", "pail", "material", "Finishing"),
        ("Upah tukang batu", "60", "OH", "labor", "Tenaga kerja"),
    ]
    for name, quantity, unit, item_type, category in lines:
        estimator.call(
            "POST",
            f"{v1}/items",
            201,
            json={
                "name": name,
                "quantity": quantity,
                "unit": unit,
                "item_type": item_type,
                "category": category,
                "price_observation_id": story.catalog[name],
            },
        )
    estimator.call(
        "POST",
        f"{v1}/items",
        201,
        json={
            "name": "Mobilisasi & demobilisasi",
            "quantity": "1",
            "unit": "ls",
            "item_type": "transport",
            "category": "Persiapan",
            "unit_price": "2500000",
            "price_source_type": "manual",
            "price_source": "Estimasi internal berdasarkan proyek serupa (Demo)",
        },
    )
    estimator.call("POST", f"{v1}/transitions/submit", json={"note": "Siap ditinjau."})
    approver.call("POST", f"{v1}/transitions/approve", json={"note": "Disetujui (Demo)."})
    document = finance.call("POST", f"{v1}/documents", 201, idempotent=True)
    story.rab_document_id = document["id"]
    # A later revision: version 2 is a draft; the issued document keeps version 1's numbers.
    estimator.call("POST", f"/rab/{rab['id']}/versions", 201, json={})
    estimator.call(
        "POST",
        f"/rab/{rab['id']}/versions/2/items",
        201,
        json={
            "name": "Pembersihan akhir",
            "quantity": "1",
            "unit": "ls",
            "item_type": "service",
            "unit_price": "1500000",
            "price_source_type": "manual",
            "price_source": "Estimasi internal (Demo)",
        },
    )

    # 3. Quotation with 30/40/30 terms, issued and accepted by the client.
    version_id = estimator.call("GET", v1)["id"]
    quotation = estimator.call("POST", "/quotations", 201, json={"rab_version_id": version_id})
    quotation = estimator.call(
        "PUT",
        f"/quotations/{quotation['id']}/terms",
        json={
            "version": quotation["version"],
            "terms": [
                {
                    "name": "Uang muka",
                    "basis": "percent",
                    "value": "30",
                    "due_date": str(today + timedelta(days=7)),
                },
                {
                    "name": "Termin 2",
                    "basis": "percent",
                    "value": "40",
                    "description": "Progres pekerjaan 70%",
                },
                {
                    "name": "Pelunasan",
                    "basis": "percent",
                    "value": "30",
                    "description": "Setelah BAST akhir",
                },
            ],
        },
    )
    story.quotation_id = quotation["id"]
    q = f"/quotations/{quotation['id']}"
    estimator.call("POST", f"{q}/transitions/submit", json={})
    approver.call("POST", f"{q}/transitions/approve", json={})
    finance.call("POST", f"{q}/issue", 201, idempotent=True)
    estimator.call(
        "POST", f"{q}/response", json={"response": "accepted", "note": "Diterima (Demo)."}
    )
    quotation = estimator.call("GET", q)

    # 4. SPK from the accepted quotation, then a partial handover (BAST).
    spk = pm.call("POST", "/spk", 201, json={"quotation_id": quotation["id"]})
    spk = pm.call(
        "PATCH",
        f"/spk/{spk['id']}",
        json={
            "version": spk["version"],
            "terms": spk["terms"],
            "title": "Renovasi Ruang Arsip Lt. 1 (Demo)",
            "start_date": str(today),
            "end_date": str(today + timedelta(days=45)),
            "location": "Gedung Arsip, Bandung (Demo)",
            "scope": "Pekerjaan struktur ringan, finishing dinding, dan mobilisasi sesuai "
            "penawaran.",
            "client_signatory_name": "Pejabat Pembuat Komitmen (Demo)",
            "client_signatory_title": "PPK",
            "company_signatory_name": "Demo Project Manager",
            "company_signatory_title": "Manajer Proyek",
        },
    )
    story.spk_id = spk["id"]
    pm.call("POST", f"/spk/{spk['id']}/transitions/submit", json={})
    approver.call("POST", f"/spk/{spk['id']}/transitions/approve", json={})
    finance.call("POST", f"/spk/{spk['id']}/issue", 201)

    progress = {row["name"]: row for row in pm.call("GET", f"/spk/{spk['id']}/progress")["items"]}
    bast = pm.call("POST", "/bast", 201, json={"spk_id": spk["id"], "kind": "partial"})
    delivered = [("Semen Portland 50 kg", "60"), ("Pasir beton", "9")]
    bast = pm.call(
        "PATCH",
        f"/bast/{bast['id']}",
        json={
            "version": bast["version"],
            "title": "BAST Tahap 1 — Material Struktur (Demo)",
            "handover_date": str(today),
            "location": "Gedung Arsip, Bandung (Demo)",
            "delivered_by_name": "Demo Project Manager",
            "delivered_by_title": "Manajer Proyek",
            "received_by_name": "Pejabat Pembuat Komitmen (Demo)",
            "received_by_title": "PPK",
            "items": [
                {
                    "rab_item_id": progress[name]["rab_item_id"],
                    "description": name,
                    "quantity": quantity,
                    "unit": progress[name]["unit"],
                    "condition": "Baik",
                }
                for name, quantity in delivered
            ],
        },
    )
    story.bast_id = bast["id"]
    pm.call("POST", f"/bast/{bast['id']}/transitions/submit", json={})
    approver.call("POST", f"/bast/{bast['id']}/transitions/approve", json={})
    finance.call("POST", f"/bast/{bast['id']}/issue", 201)

    # 5. Down-payment invoice, issued, then paid in part (a recorded transfer).
    term = quotation["payment_terms"][0]
    invoice = finance.call("POST", f"{q}/terms/{term['id']}/invoice", 201)
    if invoice["due_date"] is None:
        invoice = finance.call(
            "PATCH",
            f"/invoices/{invoice['id']}",
            json={
                "version": invoice["version"],
                "title": invoice["title"],
                "due_date": str(today + timedelta(days=14)),
                "tax_label": invoice["tax_label"],
                "tax_rate_percent": invoice["tax_rate_percent"],
            },
        )
    story.invoice_id = invoice["id"]
    finance.call("POST", f"/invoices/{invoice['id']}/transitions/submit", json={})
    approver.call("POST", f"/invoices/{invoice['id']}/transitions/approve", json={})
    finance.call("POST", f"/invoices/{invoice['id']}/issue", 201, idempotent=True)
    invoice = finance.call("GET", f"/invoices/{invoice['id']}")
    half = str((Decimal(invoice["grand_total"]) / 2).quantize(Decimal("1")))
    payment = finance.call(
        "POST",
        "/payments",
        201,
        idempotent=True,
        json={
            "client_id": invoice["client"]["id"],
            "payment_date": str(today),
            "amount": half,
            "method": "transfer",
            "reference": "TRF-DEMO-0001",
            "notes": "Pembayaran sebagian uang muka (Demo).",
            "allocations": [{"invoice_id": invoice["id"], "amount": half}],
        },
    )
    story.payment_id = payment["id"]

    # 6. A RAB waiting in the approval queue, and a draft with an unpriced line.
    laptops = projects["Pengadaan Laptop Kantor (Demo)"]
    review = estimator.call(
        "POST",
        f"/projects/{laptops['id']}/rab",
        201,
        json={"title": "RAB Pengadaan Laptop (Demo)"},
    )
    story.in_review_rab_id = review["id"]
    for body in (
        {
            "name": "Laptop 14 inci, RAM 16 GB",
            "quantity": "25",
            "unit": "unit",
            "unit_price": "11750000",
            "price_source_type": "vendor_quote",
            "price_source": "Penawaran distributor (Demo)",
        },
        {
            "name": "Instalasi sistem operasi & aplikasi kantor",
            "quantity": "25",
            "unit": "unit",
            "item_type": "service",
            "unit_price": "250000",
            "price_source_type": "manual",
            "price_source": "Tarif jasa (Demo)",
        },
    ):
        estimator.call("POST", f"/rab/{review['id']}/versions/1/items", 201, json=body)
    estimator.call("POST", f"/rab/{review['id']}/versions/1/transitions/submit", json={})

    steel = projects["Fabrikasi Rangka Baja Gudang (Demo)"]
    draft = estimator.call(
        "POST",
        f"/projects/{steel['id']}/rab",
        201,
        json={"title": "RAB Fabrikasi Rangka Baja (Demo)"},
    )
    story.draft_rab_id = draft["id"]
    for body in (
        {
            "name": "Profil WF 300",
            "quantity": "42",
            "unit": "ton",
            "unit_price": "16500000",
            "price_source_type": "vendor_quote",
            "price_source": "Penawaran pabrikan (Demo)",
        },
        # No price yet: shows how the RAB reports missing prices before it can be submitted.
        {"name": "Pengecatan anti karat", "quantity": "1", "unit": "ls", "item_type": "service"},
    ):
        estimator.call("POST", f"/rab/{draft['id']}/versions/1/items", 201, json=body)
    return story
