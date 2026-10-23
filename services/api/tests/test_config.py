from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import INSECURE_SECRET_PLACEHOLDER, Environment, Settings


def _settings(**overrides: Any) -> Settings:
    # _env_file=None isolates tests from the developer's local .env.
    return Settings(_env_file=None, **overrides)


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(app_env=Environment.PRODUCTION, secret_key=INSECURE_SECRET_PLACEHOLDER)


def test_production_rejects_short_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(app_env=Environment.PRODUCTION, secret_key="too-short")


def test_production_accepts_strong_secret() -> None:
    settings = _settings(
        app_env=Environment.PRODUCTION,
        secret_key="x" * 48,
        cors_allowed_origins=["https://rab.contoh.co.id"],
    )
    assert settings.is_production
    assert settings.cookies_secure is True


def test_production_refuses_plain_http_origins_and_insecure_cookies() -> None:
    strong = {"app_env": Environment.PRODUCTION, "secret_key": "x" * 48}
    with pytest.raises(ValidationError, match="https://"):
        _settings(**strong, cors_allowed_origins=["http://rab.contoh.co.id"])
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        _settings(
            **strong,
            cors_allowed_origins=["https://rab.contoh.co.id"],
            session_cookie_secure=False,
        )


def test_development_allows_placeholder_secret() -> None:
    assert _settings().app_env is Environment.DEVELOPMENT


def test_cors_origins_parse_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000")
    assert _settings().cors_allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_cors_wildcard_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Wildcard"):
        _settings(cors_allowed_origins=["*"])


def test_secrets_are_masked_in_repr() -> None:
    settings = _settings(database_url="postgresql+psycopg://u:topsecret@h/db")
    assert "topsecret" not in repr(settings)


def test_ai_is_disabled_by_default() -> None:
    assert _settings().ai_enabled is False
