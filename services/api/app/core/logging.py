from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SENSITIVE_KEYS = re.compile(
    r"pass(word)?|secret|token|authorization|cookie|api[_-]?key|session|csrf", re.IGNORECASE
)
# key=value / key: value pairs inside free-text messages
_INLINE_SECRET = re.compile(
    r"(?P<key>pass(?:word)?|secret|token|api[_-]?key|authorization)(?P<sep>\s*[=:]\s*)\S+",
    re.IGNORECASE,
)
# credentials embedded in connection URLs, e.g. postgresql://user:pass@host
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://[^:/@\s]+:)[^@\s]+@", re.IGNORECASE)

REDACTED = "[REDACTED]"

_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys() | {"message", "asctime"}
)


def redact_text(text: str) -> str:
    text = _URL_CREDENTIALS.sub(rf"\g<scheme>{REDACTED}@", text)
    return _INLINE_SECRET.sub(rf"\g<key>\g<sep>{REDACTED}", text)


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEYS.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    """Scrubs secrets from log messages and structured `extra` fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = None
        for key, value in list(vars(record).items()):
            if key not in _STANDARD_ATTRS:
                setattr(record, key, redact_value(key, value))
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")

    def formatException(self, ei: Any) -> str:
        return redact_text(super().formatException(ei))


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter() if json_output else TextFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn's access log includes query strings; we emit our own access line instead.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
