from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.main import create_app


class _Payload(BaseModel):
    name: str = Field(min_length=1)
    password: str


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    router = APIRouter(prefix="/api/v1/_test")

    @router.get("/missing")
    def missing() -> None:
        raise NotFoundError()

    @router.get("/conflict")
    def conflict() -> None:
        raise ConflictError("Nomor dokumen sudah dipakai.", details={"field": "number"})

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internals: password=hunter2")

    @router.post("/validate")
    def validate(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _assert_envelope(body: dict[str, object], code: str) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert error["request_id"]
    return error


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    _assert_envelope(response.json(), "not_found")


def test_app_errors_map_to_status_and_details(client: TestClient) -> None:
    assert client.get("/api/v1/_test/missing").status_code == 404

    response = client.get("/api/v1/_test/conflict")
    assert response.status_code == 409
    error = _assert_envelope(response.json(), "conflict")
    assert error["message"] == "Nomor dokumen sudah dipakai."
    assert error["details"] == {"field": "number"}


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    response = client.post("/api/v1/_test/validate", json={"name": "", "password": "hunter2"})

    assert response.status_code == 422
    error = _assert_envelope(response.json(), "validation_error")
    assert isinstance(error["details"], list)
    assert error["details"][0]["loc"] == ["body", "name"]
    assert "hunter2" not in response.text


def test_unhandled_error_hides_internals(client: TestClient) -> None:
    response = client.get("/api/v1/_test/boom", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    error = _assert_envelope(response.json(), "internal_error")
    assert error["request_id"] == "req-500"
    assert response.headers["X-Request-ID"] == "req-500"
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text
