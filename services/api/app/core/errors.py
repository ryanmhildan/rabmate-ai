"""Consistent error envelope for every API failure.

Shape: {"error": {"code": str, "message": str, "details": any | null, "request_id": str | null}}
Messages are user-facing (Bahasa Indonesia); stack traces never leave the server.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Base for expected, user-presentable errors raised by services."""

    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "bad_request"
    message: str = "Permintaan tidak valid."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details
        self.headers = headers


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "Data tidak ditemukan."


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "Data bertentangan dengan kondisi saat ini."


class PermissionDeniedError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"
    message = "Anda tidak memiliki izin untuk tindakan ini."


class AuthenticationError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthenticated"
    message = "Silakan masuk terlebih dahulu."


class InvalidCredentialsError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "invalid_credentials"
    message = "Email atau kata sandi salah."


class CsrfError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "csrf_failed"
    message = "Permintaan ditolak karena token keamanan tidak valid. Muat ulang halaman."


class RateLimitedError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Terlalu banyak percobaan. Coba lagi nanti."


class BusinessValidationError(AppError):
    """Input that is well-formed but violates a business rule."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_error"
    message = "Data yang dikirim tidak valid."


class VersionConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "version_conflict"
    message = "Data telah diubah oleh pengguna lain. Muat ulang lalu ulangi perubahan Anda."


class ServiceUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "Layanan sedang tidak tersedia."


_HTTP_CODES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "Permintaan tidak valid."),
    401: ("unauthenticated", "Silakan masuk terlebih dahulu."),
    403: ("forbidden", "Anda tidak memiliki izin untuk tindakan ini."),
    404: ("not_found", "Data tidak ditemukan."),
    405: ("method_not_allowed", "Metode tidak diizinkan."),
    409: ("conflict", "Data bertentangan dengan kondisi saat ini."),
    413: ("payload_too_large", "Ukuran data terlalu besar."),
    429: ("rate_limited", "Terlalu banyak permintaan. Coba lagi nanti."),
}


def error_response(
    status_code: int, code: str, message: str, details: Any | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, details=details, request_id=request_id_var.get()
        )
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    err = cast(AppError, exc)
    response = error_response(err.status_code, err.code, err.message, err.details)
    if err.headers:
        response.headers.update(err.headers)
    return response


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    err = cast(StarletteHTTPException, exc)
    code, message = _HTTP_CODES.get(err.status_code, ("http_error", "Terjadi kesalahan."))
    response = error_response(err.status_code, code, message)
    if err.headers:
        response.headers.update(err.headers)
    return response


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    err = cast(RequestValidationError, exc)
    # Echoing `input` back could reflect secrets (e.g. a password field); keep loc/msg/type only.
    details = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in err.errors()
    ]
    return error_response(422, "validation_error", "Data yang dikirim tidak valid.", details)


async def _stale_data_handler(_: Request, exc: Exception) -> JSONResponse:
    # Lost an optimistic-locking race between version check and UPDATE.
    return error_response(
        VersionConflictError.status_code, VersionConflictError.code, VersionConflictError.message
    )


def internal_error_response(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(500, "internal_error", "Terjadi kesalahan pada server.")


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return internal_error_response(request, exc)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StaleDataError, _stale_data_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
