from __future__ import annotations

import json
import logging

from app.core.logging import REDACTED, JsonFormatter, RedactingFilter, redact_text


def _format(record: logging.LogRecord) -> dict[str, object]:
    RedactingFilter().filter(record)
    return json.loads(JsonFormatter().format(record))  # type: ignore[no-any-return]


def _record(msg: str, *args: object, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_redacts_inline_secrets() -> None:
    assert redact_text("login password=hunter2 ok") == f"login password={REDACTED} ok"
    assert redact_text("api_key: abc123") == f"api_key: {REDACTED}"


def test_redacts_url_credentials() -> None:
    text = redact_text("connect postgresql+psycopg://rabmate:s3cret@localhost:5432/rabmate")
    assert text == f"connect postgresql+psycopg://rabmate:{REDACTED}@localhost:5432/rabmate"


def test_redacts_sensitive_extra_fields_and_args() -> None:
    payload = _format(
        _record("user %s logged in with %s", "budi", "token=xyz", authorization="Bearer abc")
    )
    assert payload["authorization"] == REDACTED
    assert "xyz" not in str(payload["msg"])
    assert "budi" in str(payload["msg"])


def test_redacts_nested_dict_values() -> None:
    payload = _format(_record("event", context={"user": "budi", "password": "p", "n": 1}))
    assert payload["context"] == {"user": "budi", "password": REDACTED, "n": 1}
