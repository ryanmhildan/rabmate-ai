"""Phase 9 API with a fake agent and fake OCR: source documents, document extraction, chat."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.adapter import AgentUnavailableError
from app.ai.runtime import get_agent_adapter, get_session_factory, reset_health_cache
from app.api.deps import RequestContext
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.modules.assistant import chat
from app.modules.assistant.models import AiMessage, AiRun, AiRunKind, AiRunStatus
from app.modules.identity.models import Membership, UserSession
from app.modules.identity.permissions import Permission, Role
from app.modules.intake.router import get_ocr_engine
from app.modules.rab.models import RabItem
from tests.factories import LoginAs, Tenant, make_project, make_user
from tests.intake_files import FakeOcr, scanned_pdf, table_pdf, xlsx
from tests.test_ai_api import FakeAgent
from tests.test_pricing_api import add_price, make_item
from tests.test_rab_api import Rab, ok

PDF = table_pdf()
EXTRACT_REPLY = {
    "items": [
        {
            "name": "Kabel UTP Cat6 Belden",
            "quantity_text": "305",
            "unit": "m",
            "unit_price_text": "4.300",
            "total_text": "1.311.500",
            "source_line": 3,
        },
        {
            "name": "Konektor RJ45",
            "quantity_text": "100",
            "unit": "pcs",
            "unit_price_text": "2.500",
            "total_text": "250.000",
            "source_line": 2,  # the document's "No" column; corrected to line 4 by name
        },
    ]
}


@pytest.fixture(autouse=True)
def _fresh_health() -> Iterator[None]:
    reset_health_cache()
    yield
    reset_health_cache()


@pytest.fixture
def fake_agent() -> FakeAgent:
    return FakeAgent()


@pytest.fixture
def fake_ocr() -> FakeOcr:
    return FakeOcr(available=False)


@pytest.fixture
def ai_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"ai_enabled": True, "hermes_api_key": SecretStr("uji")})


@pytest.fixture
def app(
    ai_settings: Settings, db_session: Session, fake_agent: FakeAgent, fake_ocr: FakeOcr
) -> FastAPI:
    application = create_app(ai_settings)

    def shared_session() -> Iterator[Session]:
        try:
            yield db_session
        except Exception:
            db_session.rollback()
            raise

    @contextmanager
    def background_session() -> Iterator[Session]:
        yield db_session

    application.dependency_overrides[get_db] = shared_session
    application.dependency_overrides[get_agent_adapter] = lambda: fake_agent
    application.dependency_overrides[get_session_factory] = lambda: background_session
    application.dependency_overrides[get_ocr_engine] = lambda: fake_ocr
    return application


@pytest.fixture
def estimator(db_session: Session, tenant: Tenant, login_as: LoginAs) -> TestClient:
    return login_as(make_user(db_session, tenant.org, Role.ESTIMATOR))


@pytest.fixture
def rab(db_session: Session, tenant: Tenant, estimator: TestClient) -> Rab:
    project = make_project(db_session, tenant.org, name="Kantor Cabang Bandung", currency="IDR")
    created = ok(
        estimator.post(f"/api/v1/projects/{project.id}/rab", json={"title": "RAB Jaringan"}), 201
    )
    rab = Rab(estimator, created)
    ok(rab.add(name="Rak server", quantity="1", unit="unit", unit_price="2500000"), 201)
    return rab


def project_of(rab: Rab) -> str:
    return str(ok(rab.browser.get(f"/api/v1/rab/{rab.id}"))["project"]["id"])


def upload(
    browser: TestClient, project_id: str, name: str, content: bytes, content_type: str = "x"
) -> Any:
    return browser.post(
        f"/api/v1/projects/{project_id}/source-documents",
        files={"file": (name, content, content_type)},
    )


def extract(browser: TestClient, rab: Rab, document_id: str, **body: Any) -> Any:
    return browser.post(
        rab.url(1, "/ai-runs"),
        json={"kind": "extract_document", "source_document_id": document_id, **body},
    )


def run_of(browser: TestClient, run: dict[str, Any]) -> Any:
    return ok(browser.get(f"/api/v1/ai-runs/{run['id']}"))


# --------------------------------------------------------------------------- source documents


def test_upload_dedup_list_download_and_text(estimator: TestClient, rab: Rab) -> None:
    project_id = project_of(rab)
    first = ok(upload(estimator, project_id, "../Penawaran Mei.pdf", PDF), 201)
    assert (first["filename"], first["kind"], first["duplicate"]) == (
        "Penawaran Mei.pdf",
        "pdf",
        False,
    )
    again = ok(upload(estimator, project_id, "salinan.pdf", PDF), 201)
    assert (again["id"], again["duplicate"], again["filename"]) == (
        first["id"],
        True,
        "Penawaran Mei.pdf",
    )
    listed = ok(estimator.get(f"/api/v1/projects/{project_id}/source-documents"))
    assert [d["id"] for d in listed] == [first["id"]]

    download = estimator.get(f"/api/v1/source-documents/{first['id']}/file")
    assert download.status_code == 200
    assert download.content == PDF
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["content-disposition"] == (
        "attachment; filename=\"Penawaran Mei.pdf\"; filename*=UTF-8''Penawaran%20Mei.pdf"
    )
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "no-store"
    assert ok(estimator.get(f"/api/v1/source-documents/{first['id']}/text")) == {
        "read": False,
        "pages": [],
        "warnings": [],
    }


def test_upload_refuses_wrong_large_or_disguised_files(
    estimator: TestClient, rab: Rab, app: FastAPI, ai_settings: Settings
) -> None:
    project_id = project_of(rab)
    disguised = upload(estimator, project_id, "penawaran.pdf", b"MZ\x90\x00program")
    assert disguised.status_code == 422
    assert "Format tidak didukung" in disguised.json()["error"]["message"]
    mismatch = upload(estimator, project_id, "harga.xlsx", PDF)
    assert mismatch.status_code == 422
    assert upload(estimator, project_id, "kosong.csv", b"").status_code == 422

    limit = ai_settings.upload_max_mb * 1024 * 1024
    big = upload(estimator, project_id, "besar.pdf", b"%PDF-" + b"0" * limit)
    assert big.status_code == 413
    assert big.json()["error"]["code"] == "payload_too_large"


def test_source_document_permissions_and_isolation(
    estimator: TestClient,
    rab: Rab,
    db_session: Session,
    tenant: Tenant,
    other_tenant: Tenant,
    login_as: LoginAs,
) -> None:
    project_id = project_of(rab)
    doc = ok(upload(estimator, project_id, "penawaran.pdf", PDF), 201)
    for role in (Role.VIEWER, Role.APPROVER, Role.FINANCE):
        browser = login_as(make_user(db_session, tenant.org, role))
        assert upload(browser, project_id, "x.pdf", table_pdf(title="X")).status_code == 403
        assert browser.get(f"/api/v1/source-documents/{doc['id']}/file").status_code == 200

    stranger = other_tenant.browser
    for url in (
        f"/api/v1/projects/{project_id}/source-documents",
        f"/api/v1/source-documents/{doc['id']}",
        f"/api/v1/source-documents/{doc['id']}/file",
        f"/api/v1/source-documents/{doc['id']}/text",
    ):
        assert stranger.get(url).status_code == 404, url
    assert upload(stranger, project_id, "x.pdf", PDF).status_code == 404


# --------------------------------------------------------------------------- document extraction


def test_document_extraction_cites_pages_and_applies_with_the_document_as_source(
    estimator: TestClient, rab: Rab, fake_agent: FakeAgent, db_session: Session
) -> None:
    doc = ok(upload(estimator, project_of(rab), "penawaran.pdf", PDF), 201)
    fake_agent.replies = [json.dumps(EXTRACT_REPLY)]
    queued = ok(extract(estimator, rab, doc["id"], number_format="id"), 202)
    assert queued["source_document_id"] == doc["id"]
    assert queued["context"]["document"]["filename"] == "penawaran.pdf"

    run = run_of(estimator, queued)
    assert run["status"] == "succeeded", run["error_message"]
    kabel, konektor = run["result"]["items"]
    assert (kabel["source_page"], kabel["source_page_line"], kabel["total"]) == (
        "Halaman 1",
        3,
        "1311500",
    )
    assert (konektor["source_line"], konektor["source_page_line"]) == (4, 4)
    assert run["result"]["document"] == {
        "pages": 1,
        "lines": 4,
        "chunks": 1,
        "ocr_pages": 0,
        "lines_left_out": 0,
    }
    prompt = fake_agent.requests[0].messages[0].content
    assert "Dokumen: penawaran.pdf" in prompt
    assert "--- Halaman 1 ---\n[1] PENAWARAN CV SUMBER JAYA" in prompt

    text = ok(estimator.get(f"/api/v1/source-documents/{doc['id']}/text"))
    assert text["read"] is True
    assert text["pages"][0]["lines"][2].startswith("1 | Kabel UTP Cat6 Belden")

    ok(
        estimator.post(
            f"/api/v1/ai-runs/{run['id']}/apply",
            json={
                "items": [
                    {
                        "index": 0,
                        "name": "Kabel UTP Cat6 Belden",
                        "quantity": "305",
                        "unit": "m",
                        "price": "document",
                    },
                    {"index": 1, "name": "Konektor RJ45", "quantity": "100", "unit": "pcs"},
                ]
            },
        )
    )
    version_id = uuid.UUID(rab.version()["id"])
    kabel_item, konektor_item = db_session.execute(
        select(RabItem)
        .where(RabItem.version_id == version_id, RabItem.name != "Rak server")
        .order_by(RabItem.position)
    ).scalars()
    assert kabel_item.price_source == (
        "Dokumen 'penawaran.pdf', Halaman 1, baris 3 — diekstrak AI lokal, belum diverifikasi"
    )
    assert konektor_item.unit_price is None
    assert "Sumber: Dokumen 'penawaran.pdf', Halaman 1, baris 4." in (konektor_item.notes or "")


def test_long_documents_are_chunked_and_a_bad_chunk_only_costs_its_part(
    estimator: TestClient,
    rab: Rab,
    fake_agent: FakeAgent,
    app: FastAPI,
    ai_settings: Settings,
) -> None:
    header = ["No", "Uraian", "Volume", "Satuan", "Harga"]
    rows = [header] + [[n, f"Barang nomor {n}", n, "unit", 1000 * n] for n in range(1, 121)]
    content = xlsx(rows)
    doc = ok(upload(estimator, project_of(rab), "boq.xlsx", content), 201)
    app.dependency_overrides[get_settings] = lambda: ai_settings.model_copy(
        update={"ai_chunk_chars": 2000, "ai_max_chunks": 2, "ai_max_retries": 1}
    )
    first = {
        "items": [
            {
                "name": "Barang nomor 1",
                "quantity_text": "1",
                "unit": "unit",
                "unit_price_text": "1.000",
                "source_line": 2,
            }
        ]
    }
    fake_agent.replies = [json.dumps(first), "bukan json", "masih bukan json"]
    # number_format "en" is ignored for spreadsheets: the reader writes cells in ID notation.
    run = run_of(estimator, ok(extract(estimator, rab, doc["id"], number_format="en"), 202))
    assert run["input"]["number_format"] == "id"
    assert run["status"] == "succeeded"
    assert [i["unit_price"] for i in run["result"]["items"]] == ["1000"]
    document = run["result"]["document"]
    assert (document["chunks"], document["lines"]) == (2, 121)
    assert document["lines_left_out"] > 0
    warnings = " ".join(run["result"]["warnings"])
    assert "Dokumen terlalu panjang untuk sekali proses" in warnings
    assert "tidak sesuai format; periksa bagian itu secara manual" in warnings
    assert len(fake_agent.requests) == 3
    second_part = fake_agent.requests[1].messages[0].content
    assert "Bagian 2 dari 2" in second_part
    assert "Kepala tabel dari bagian sebelumnya (tanpa nomor, bukan item): No | Uraian" in (
        second_part
    )


def test_scans_without_ocr_fail_clearly_and_with_ocr_are_read(
    estimator: TestClient, rab: Rab, fake_agent: FakeAgent, fake_ocr: FakeOcr
) -> None:
    doc = ok(upload(estimator, project_of(rab), "scan.pdf", scanned_pdf()), 201)
    failed = run_of(estimator, ok(extract(estimator, rab, doc["id"]), 202))
    assert (failed["status"], failed["error_code"]) == ("failed", "document_empty")
    assert "OCR tidak tersedia" in failed["error_message"]
    assert fake_agent.requests == []

    # The read text is cached per document; a second scan (other bytes) goes through OCR.
    fake_ocr.available = True
    fake_ocr.text = "1  Semen 50 kg  12  zak  65.000"
    scan2 = ok(upload(estimator, project_of(rab), "scan2.pdf", scanned_pdf() + b"\n"), 201)
    fake_agent.replies = [
        json.dumps(
            {
                "items": [
                    {
                        "name": "Semen 50 kg",
                        "quantity_text": "12",
                        "unit": "zak",
                        "unit_price_text": "65.000",
                        "source_line": 1,
                    }
                ]
            }
        )
    ]
    run = run_of(estimator, ok(extract(estimator, rab, scan2["id"]), 202))
    assert run["status"] == "succeeded", run["error_message"]
    assert run["result"]["document"]["ocr_pages"] == 1
    assert run["result"]["items"][0]["unit_price"] == "65000"


def test_documents_must_belong_to_the_rab_project_and_organization(
    estimator: TestClient,
    rab: Rab,
    db_session: Session,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    other_project = make_project(db_session, tenant.org, name="Proyek Lain")
    elsewhere = ok(upload(estimator, str(other_project.id), "lain.pdf", PDF), 201)
    refused = extract(estimator, rab, elsewhere["id"])
    assert refused.status_code == 422
    assert "proyek lain" in refused.json()["error"]["message"]

    foreign_project = make_project(db_session, other_tenant.org, name="Asing")
    foreign = ok(upload(other_tenant.browser, str(foreign_project.id), "asing.pdf", PDF), 201)
    assert extract(estimator, rab, foreign["id"]).status_code == 404
    assert extract(estimator, rab, str(uuid.uuid4())).status_code == 404
    missing = estimator.post(rab.url(1, "/ai-runs"), json={"kind": "extract_document"})
    assert missing.status_code == 422


def test_status_reports_ocr_and_upload_limits(estimator: TestClient) -> None:
    status = ok(estimator.get("/api/v1/ai/status"))
    assert status["ocr"] == {"available": False, "message": "OCR tidak tersedia (uji)."}
    assert status["upload_max_mb"] == 10
    assert ".pdf" in status["accepted_files"]


# --------------------------------------------------------------------------- project chat


def chat_reply(answer: str, **extra: Any) -> str:
    return json.dumps({"answer": answer, **extra})


def start(browser: TestClient, project_id: str, message: str) -> Any:
    return browser.post(
        f"/api/v1/projects/{project_id}/ai-conversations", json={"message": message}
    )


def test_chat_answers_from_cited_sources_and_flags_what_it_cannot_back(
    estimator: TestClient, rab: Rab, fake_agent: FakeAgent, db_session: Session
) -> None:
    item = make_item(estimator, name="Kabel UTP Cat6 Belden", unit="m")
    add_price(estimator, item["id"], price="4300")
    project_id = project_of(rab)
    fake_agent.replies = [
        chat_reply(
            "Rak server Rp 2.500.000 [S2]. Kabel Rp 4.300/m [S3] belum diverifikasi. "
            "Total kabel Rp 9.999.999 [S7].",
            assumptions=["Harga belum termasuk PPN."],
            questions=["Berapa meter kabel yang dibutuhkan?"],
        )
    ]
    started = ok(start(estimator, project_id, "Berapa harga kabel UTP dan rak server?"), 202)
    assert started["title"] == "Berapa harga kabel UTP dan rak server?"

    conversation = ok(estimator.get(f"/api/v1/ai-conversations/{started['id']}"))
    assert conversation["latest_run"]["status"] == "succeeded"
    question, answer = conversation["messages"]
    assert (question["role"], answer["role"]) == ("user", "assistant")
    assert answer["content"] == (
        "Rak server Rp 2.500.000 [S2]. Kabel Rp 4.300/m [S3] belum diverifikasi. "
        "Total kabel Rp 9.999.999."
    )
    assert [s["id"] for s in answer["sources"]] == ["S2", "S3"]
    assert answer["sources"][0]["ref"]["type"] == "rab"
    assert answer["sources"][1]["data"]["price"]["status"] == "belum diverifikasi"
    assert answer["sources"][1]["data"]["price"]["price"] == "Rp 4.300"
    assert answer["warnings"] == [
        "Kutipan S7 tidak merujuk ke sumber yang tersedia; dihapus.",
        "Angka 9.999.999 tidak ditemukan di data sumber (bisa hasil hitungan atau karangan AI). "
        "Periksa sebelum dipakai.",
    ]
    assert answer["assumptions"] == ["Harga belum termasuk PPN."]
    assert answer["questions"] == ["Berapa meter kabel yang dibutuhkan?"]
    assert conversation["unavailable"] == [
        "Invoice dan pembayaran (Anda tidak memiliki izin keuangan)."
    ]

    prompt = fake_agent.requests[0].messages[-1].content
    data = prompt.split("<<<SUMBER>>>\n", 1)[1].split("<<<AKHIR SUMBER>>>")[0]
    headers = [line for line in data.splitlines() if line.startswith("[S")]
    assert [h.split(" ", 2)[:2] for h in headers] == [
        ["[S1]", "Proyek"],
        ["[S2]", rab.number],
        ["[S3]", "Katalog:"],
    ]
    assert "1. Rak server — 1 unit — harga satuan Rp 2.500.000" in data
    assert rab.id not in prompt and item["id"] not in prompt  # database ids stay out

    # A follow-up carries the previous turn, without its old citation markers.
    fake_agent.replies = [chat_reply("RAB masih draft; rak server Rp 2.500.000 [S1].")]
    ok(
        estimator.post(
            f"/api/v1/ai-conversations/{started['id']}/messages",
            json={"message": "Apakah RAB-nya sudah disetujui?"},
        ),
        202,
    )
    history = fake_agent.requests[1].messages[:-1]
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == (
        "Rak server Rp 2.500.000. Kabel Rp 4.300/m belum diverifikasi. Total kabel Rp 9.999.999."
    )
    assert history[0].content == "Berapa harga kabel UTP dan rak server?"
    follow_up = ok(estimator.get(f"/api/v1/ai-conversations/{started['id']}"))["messages"][-1]
    # The amount came from the RAB, not from the cited project: shown, marked as not cited.
    assert [(s["id"], s["cited"]) for s in follow_up["sources"]] == [("S1", True), ("S2", False)]
    assert follow_up["warnings"][0].startswith("Angka 2.500.000 berasal dari [S2]")
    listed = ok(estimator.get(f"/api/v1/projects/{project_id}/ai-conversations"))
    assert [(c["id"], c["message_count"]) for c in listed] == [(started["id"], 4)]


def test_chat_is_private_and_needs_ai_use(
    estimator: TestClient,
    rab: Rab,
    fake_agent: FakeAgent,
    db_session: Session,
    tenant: Tenant,
    other_tenant: Tenant,
    login_as: LoginAs,
) -> None:
    project_id = project_of(rab)
    fake_agent.replies = [chat_reply("Proyek di Bandung [S1].")]
    started = ok(start(estimator, project_id, "Di mana lokasi proyek?"), 202)
    url = f"/api/v1/ai-conversations/{started['id']}"

    colleague = login_as(make_user(db_session, tenant.org, Role.PROJECT_MANAGER))
    assert colleague.get(url).status_code == 404
    assert colleague.post(f"{url}/messages", json={"message": "Halo?"}).status_code == 404
    assert colleague.delete(url).status_code == 404
    assert ok(colleague.get(f"/api/v1/projects/{project_id}/ai-conversations")) == []
    assert other_tenant.browser.get(url).status_code == 404
    for role in (Role.VIEWER, Role.APPROVER, Role.FINANCE):
        browser = login_as(make_user(db_session, tenant.org, role))
        assert start(browser, project_id, "Halo, ada apa?").status_code == 403, role
    assert len(fake_agent.requests) == 1

    # Chat answers are not reachable through the RAB run endpoints either.
    run_id = db_session.execute(
        select(AiRun.id).where(AiRun.kind == AiRunKind.CHAT_ANSWER)
    ).scalar_one()
    assert estimator.get(f"/api/v1/ai-runs/{run_id}").status_code == 404

    assert estimator.delete(url).status_code == 204
    assert estimator.get(url).status_code == 404
    assert db_session.execute(select(AiMessage)).first() is None


def test_chat_retrieval_follows_the_users_permissions(
    db_session: Session, tenant: Tenant, rab: Rab
) -> None:
    project_id = uuid.UUID(project_of(rab))
    membership = db_session.execute(
        select(Membership).where(Membership.user_id == tenant.owner.id)
    ).scalar_one()
    ctx = RequestContext(
        user=tenant.owner,
        organization=tenant.org,
        membership=membership,
        session=cast(UserSession, None),
        permissions=frozenset({Permission.AI_USE, Permission.PROJECTS_READ}),
        ip_address=None,
    )
    sources, unavailable = chat.gather_sources(db_session, ctx, project_id, "harga kabel")
    assert [s["kind"] for s in sources] == ["proyek"]
    assert unavailable == [
        "Data RAB (Anda tidak memiliki izin melihat RAB).",
        "Katalog harga (Anda tidak memiliki izin melihat katalog).",
        "Invoice dan pembayaran (Anda tidak memiliki izin keuangan).",
    ]


def test_chat_failures_are_shown_and_a_busy_conversation_waits(
    estimator: TestClient, rab: Rab, fake_agent: FakeAgent, db_session: Session
) -> None:
    project_id = project_of(rab)
    fake_agent.replies = [AgentUnavailableError("Hermes tidak dapat dihubungi.")]
    started = ok(start(estimator, project_id, "Berapa total RAB?"), 202)
    url = f"/api/v1/ai-conversations/{started['id']}"
    failed = ok(estimator.get(url))
    assert failed["latest_run"]["status"] == "failed"
    assert failed["latest_run"]["error_message"] == "Hermes tidak dapat dihubungi."
    assert [m["role"] for m in failed["messages"]] == ["user"]

    run = db_session.execute(select(AiRun).where(AiRun.kind == AiRunKind.CHAT_ANSWER)).scalar_one()
    run.status = AiRunStatus.RUNNING
    db_session.commit()
    busy = estimator.post(f"{url}/messages", json={"message": "Lagi?"})
    assert busy.status_code == 409
    assert estimator.delete(url).status_code == 409

    fake_agent.state = fake_agent.state.UNAVAILABLE
    run.status = AiRunStatus.FAILED
    db_session.commit()
    reset_health_cache()
    down = estimator.post(f"{url}/messages", json={"message": "Lagi?"})
    assert down.status_code == 503
    assert estimator.post(f"{url}/messages", json={"message": "x"}).status_code == 422
