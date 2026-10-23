from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import error_response, internal_error_response, register_error_handlers
from app.core.logging import configure_logging, request_id_var

access_logger = logging.getLogger("app.access")

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
# JSON is data, never a page: nothing may load from or frame it. Not set on PDF/XLSX responses,
# where it could interfere with the browser's built-in PDF viewer.
JSON_CSP = "default-src 'none'; frame-ancestors 'none'"
# Only honoured over HTTPS (behind the TLS-terminating proxy in production).
HSTS = "max-age=31536000; includeSubDomains"


UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _foreign_origin(request: Request, settings: Settings) -> bool:
    """Defense in depth next to CSRF tokens: browsers always send Origin on cross-site writes.

    Requests without an Origin header (curl, server-to-server, tests) still need a valid
    session + CSRF token for authenticated endpoints.
    """
    if request.method not in UNSAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    return origin is not None and origin not in settings.cors_allowed_origins


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    docs_enabled = settings.enable_api_docs and not settings.is_production
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        openapi_url="/api/v1/openapi.json" if docs_enabled else None,
        docs_url="/api/v1/docs" if docs_enabled else None,
        redoc_url=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    register_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response: Response
        try:
            try:
                if _foreign_origin(request, settings):
                    response = error_response(
                        403, "origin_rejected", "Permintaan dari situs lain ditolak."
                    )
                else:
                    response = await call_next(request)
            except Exception as exc:
                # Handled here (not only in the app-level handler) so the 500 response
                # still carries the request id and security headers.
                response = internal_error_response(request, exc)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            for header, value in SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)
            if response.headers.get("content-type", "").startswith("application/json"):
                response.headers.setdefault("Content-Security-Policy", JSON_CSP)
            if settings.is_production:
                response.headers.setdefault("Strict-Transport-Security", HSTS)
            return response
        finally:
            # Path only: query strings can carry search terms or tokens.
            access_logger.info(
                "%s %s %s %.1fms",
                request.method,
                request.url.path,
                status_code,
                (time.perf_counter() - started) * 1000,
            )
            request_id_var.reset(token)

    app.include_router(api_router)
    return app


app = create_app()
