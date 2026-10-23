"""Phase 10 hardening: limits on expensive requests and response security headers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Environment, Settings
from app.core.ratelimit import WINDOW_SECONDS, SlidingWindow, expensive_window
from app.db.session import get_db
from app.main import HSTS, JSON_CSP, create_app
from app.modules.identity.permissions import Role
from tests.factories import Tenant, login, make_project, make_user
from tests.test_rab_api import Rab, ok


@pytest.fixture(autouse=True)
def _fresh_window() -> Iterator[None]:
    expensive_window.clear()
    yield
    expensive_window.clear()


def test_sliding_window_counts_per_key_and_frees_up_over_time() -> None:
    window = SlidingWindow()
    assert window.hit("a", 2, now=0.0) is None
    assert window.hit("a", 2, now=10.0) is None
    assert window.hit("a", 2, now=20.0) == pytest.approx(WINDOW_SECONDS - 20.0)
    assert window.hit("b", 2, now=20.0) is None  # other users have their own budget
    assert window.hit("a", 2, now=WINDOW_SECONDS + 0.5) is None  # the first hit expired


def _limited_app(settings: Settings, db_session: Session, per_minute: int) -> FastAPI:
    app = create_app(settings.model_copy(update={"rate_limit_expensive_per_minute": per_minute}))

    def shared_session() -> Iterator[Session]:
        try:
            yield db_session
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = shared_session
    return app


def _rab(browser: TestClient, project_id: str) -> Rab:
    created = ok(browser.post(f"/api/v1/projects/{project_id}/rab", json={"title": "RAB"}), 201)
    rab = Rab(browser, created)
    ok(rab.add(name="Semen", quantity="10", unit="sak", unit_price="65000"), 201)
    return rab


def test_expensive_requests_are_limited_per_user(
    settings: Settings, db_session: Session, tenant: Tenant
) -> None:
    app = _limited_app(settings, db_session, per_minute=2)
    owner = TestClient(app)
    assert login(owner, tenant.owner.email).status_code == 200
    project = make_project(db_session, tenant.org)
    rab = _rab(owner, str(project.id))

    assert owner.get(rab.url(1, "/preview.pdf")).status_code == 200
    assert owner.get(rab.url(1, "/export.xlsx")).status_code == 200
    limited = owner.get(rab.url(1, "/preview.pdf"))
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    # Cheap requests are not counted.
    assert owner.get(rab.url(1)).status_code == 200

    colleague = TestClient(app)
    user = make_user(db_session, tenant.org, Role.ESTIMATOR)
    assert login(colleague, user.email).status_code == 200
    assert colleague.get(rab.url(1, "/preview.pdf")).status_code == 200


def test_rate_limit_can_be_switched_off(
    settings: Settings, db_session: Session, tenant: Tenant
) -> None:
    app = _limited_app(settings, db_session, per_minute=0)
    owner = TestClient(app)
    assert login(owner, tenant.owner.email).status_code == 200
    rab = _rab(owner, str(make_project(db_session, tenant.org).id))
    for _ in range(5):
        assert owner.get(rab.url(1, "/preview.pdf")).status_code == 200


def test_json_responses_forbid_loading_and_framing(bare_client: TestClient) -> None:
    response = bare_client.get("/api/v1/health/live")
    assert response.headers["Content-Security-Policy"] == JSON_CSP
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "Strict-Transport-Security" not in response.headers  # development: plain HTTP


def test_files_keep_the_pdf_viewer_working(
    app_client: TestClient, tenant: Tenant, db_session: Session
) -> None:
    rab = _rab(tenant.browser, str(make_project(db_session, tenant.org).id))
    pdf = tenant.browser.get(rab.url(1, "/preview.pdf"))
    assert pdf.headers["content-type"] == "application/pdf"
    assert "Content-Security-Policy" not in pdf.headers
    assert pdf.headers["X-Content-Type-Options"] == "nosniff"


def test_production_responses_require_https(settings: Settings) -> None:
    production = settings.model_copy(update={"app_env": Environment.PRODUCTION})
    with TestClient(create_app(production)) as client:
        response = client.get("/api/v1/health/live")
    assert response.headers["Strict-Transport-Security"] == HSTS
