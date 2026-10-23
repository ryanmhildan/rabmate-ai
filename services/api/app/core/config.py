from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]

# Placeholder shipped in .env.example; refused outside development/test.
INSECURE_SECRET_PLACEHOLDER = "change-me-in-.env"  # noqa: S105 - sentinel, not a secret


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-wide .env first, then an optional service-local override.
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RABmate AI"
    app_env: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = False

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://rabmate:rabmate@127.0.0.1:5432/rabmate"
    )
    test_database_url: SecretStr = SecretStr(
        "postgresql+psycopg://rabmate:rabmate@127.0.0.1:5432/rabmate_test"
    )
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    secret_key: SecretStr = SecretStr(INSECURE_SECRET_PLACEHOLDER)
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    enable_api_docs: bool = True

    timezone: str = "Asia/Jakarta"
    default_currency: str = "IDR"

    # Sessions (server-side, opaque cookie token). Secure cookies default to on in production.
    session_max_age_hours: int = Field(default=168, ge=1, le=24 * 30)
    session_idle_timeout_minutes: int = Field(default=480, ge=5, le=24 * 60 * 7)
    session_cookie_secure: bool | None = None

    # Peers allowed to set X-Forwarded-For (the Next.js server that rewrites /api/*).
    trusted_proxy_ips: Annotated[list[str], NoDecode] = ["127.0.0.1", "::1"]

    # Login throttling, counted from the login_attempts table (survives restarts).
    login_window_minutes: int = Field(default=15, ge=1, le=24 * 60)
    login_max_failures_per_email: int = Field(default=5, ge=1, le=100)
    login_max_failures_per_ip: int = Field(default=20, ge=1, le=1000)
    # Per-user requests per minute to endpoints that render files, issue documents, take uploads
    # or call the local model (0 = off). In process memory; see app/core/ratelimit.py.
    rate_limit_expensive_per_minute: int = Field(default=30, ge=0, le=10_000)

    # External price search provider. "none" = not configured (no fake results, ever).
    price_search_provider: Literal["none"] = "none"

    # Local AI through Hermes Agent's API server (ADR-040). Never falls back to a cloud provider.
    ai_enabled: bool = False
    # Must be a loopback address: business data never leaves this machine through the adapter.
    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_api_key: SecretStr = SecretStr("")
    # The "model" Hermes exposes = the profile name (API_SERVER_MODEL_NAME), e.g. "rabmate".
    hermes_model: str = Field(default="rabmate", min_length=1, max_length=100)
    # Toolsets the Hermes profile may have enabled; anything else (terminal, file, web, ...) makes
    # the adapter refuse to run. Empty: structured workflows need no agent tools at all.
    hermes_allowed_toolsets: Annotated[list[str], NoDecode] = []
    ai_request_timeout_seconds: int = Field(default=120, ge=5, le=900)
    # Model calls per run: 1 + this many retries (transient errors, or one repair attempt for
    # output that fails validation). Bounded so a broken model cannot loop.
    ai_max_retries: int = Field(default=1, ge=0, le=2)
    ai_max_input_chars: int = Field(default=20_000, ge=1_000, le=100_000)
    ai_max_output_chars: int = Field(default=60_000, ge=1_000, le=500_000)
    # Long documents are sent to the model in bounded parts (each a separate call).
    ai_chunk_chars: int = Field(default=12_000, ge=2_000, le=60_000)
    ai_max_chunks: int = Field(default=6, ge=1, le=30)

    # Uploaded source documents for extraction (ADR-043).
    upload_max_mb: int = Field(default=10, ge=1, le=50)
    intake_max_pages: int = Field(default=50, ge=1, le=500)
    # OCR for scanned pages and images: Tesseract, detected at runtime. Off or not installed =
    # those pages are reported as unreadable (never guessed).
    ocr_enabled: bool = True
    tesseract_cmd: str | None = None
    ocr_languages: str = Field(default="ind+eng", pattern=r"^[a-z_]{3,}(\+[a-z_]{3,})*$")
    ocr_timeout_seconds: int = Field(default=60, ge=5, le=600)
    ocr_max_pages: int = Field(default=20, ge=1, le=200)

    @field_validator(
        "cors_allowed_origins", "trusted_proxy_ips", "hermes_allowed_toolsets", mode="before"
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("Wildcard CORS origin is not allowed; list explicit origins.")
        return value

    @field_validator("hermes_base_url")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not host:
            raise ValueError("HERMES_BASE_URL harus berupa URL http(s).")
        loopback = host == "localhost"
        if not loopback:
            try:
                loopback = ip_address(host).is_loopback
            except ValueError:
                loopback = False
        if not loopback:
            raise ValueError(
                "HERMES_BASE_URL harus alamat lokal (127.0.0.1/localhost): data bisnis tidak "
                "boleh dikirim ke layanan di luar komputer ini."
            )
        return value.rstrip("/")

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.app_env is Environment.PRODUCTION:
            secret = self.secret_key.get_secret_value()
            if secret == INSECURE_SECRET_PLACEHOLDER or len(secret) < 32:
                raise ValueError("SECRET_KEY must be set to a random value of 32+ characters.")
            if self.session_cookie_secure is False:
                raise ValueError("SESSION_COOKIE_SECURE cannot be false in production (use HTTPS).")
            plain = [o for o in self.cors_allowed_origins if not o.startswith("https://")]
            if plain:
                listed = ", ".join(plain)
                raise ValueError(f"CORS_ALLOWED_ORIGINS must be https:// in production: {listed}")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def cookies_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
