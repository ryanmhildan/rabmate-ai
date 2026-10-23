from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import build_engine, get_db
from app.main import SECURITY_HEADERS, create_app


def test_health_reports_database_ok(app_client: TestClient) -> None:
    response = app_client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["ai"] == "disabled"
    assert body["environment"] == "test"
    assert body["time"].endswith("+07:00"), "time must be reported in Asia/Jakarta"


def test_live_does_not_need_database(bare_client: TestClient) -> None:
    response = bare_client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_503_when_database_unreachable(settings: Settings) -> None:
    # Port 1 on loopback refuses connections immediately; no real database involved.
    engine = build_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none_test", connect_timeout=1
    )
    factory = sessionmaker(bind=engine)

    def broken_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app(settings)
    app.dependency_overrides[get_db] = broken_db
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    engine.dispose()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "error"
    assert "nothing" not in response.text, "credentials must never leak into responses"


def test_responses_carry_request_id_and_security_headers(bare_client: TestClient) -> None:
    response = bare_client.get("/api/v1/health/live", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


def test_malformed_request_id_is_replaced(bare_client: TestClient) -> None:
    for bad in ("bad id <script>", "x" * 65):
        response = bare_client.get("/api/v1/health/live", headers={"X-Request-ID": bad})

        request_id = response.headers["X-Request-ID"]
        assert request_id != bad
        assert len(request_id) == 32
