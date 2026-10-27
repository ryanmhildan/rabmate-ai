"""Adapter for Hermes Agent's API server (OpenAI-compatible), verified against v0.22.x docs.

Documented behaviour this relies on (docs/DECISIONS.md ADR-040):
- `GET /health` (no auth), `GET /v1/toolsets` and `POST /v1/chat/completions` (Bearer key).
- Requests run with the profile's enabled toolsets, and the API offers no per-request way to
  turn them off. So before every run the adapter reads `/v1/toolsets` and refuses to send
  anything if a toolset outside `HERMES_ALLOWED_TOOLSETS` is enabled (terminal, file, web, ...).
  An endpoint that cannot be verified counts as unsafe (fail closed).

Guarantees: only the configured loopback URL is ever called (validated in Settings), the system
proxy is ignored, there is no other provider to fall back to, timeouts are explicit and retries
bounded. Logs carry status codes and durations only — never prompts or replies.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

import httpx2

from app.ai.adapter import (
    AgentAdapter,
    AgentHealth,
    AgentReply,
    AgentRequest,
    AgentResponseError,
    AgentState,
    AgentTimeoutError,
    AgentUnavailableError,
    AgentUnsafeConfigError,
)
from app.core.config import Settings

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


def enabled_toolsets(payload: Any) -> list[str] | None:
    """Names of enabled toolsets in a `/v1/toolsets` body; None when the shape is unknown."""
    entries: Any = payload
    if isinstance(payload, dict):
        entries = payload.get("toolsets", payload.get("data"))
    if not isinstance(entries, list):
        return None
    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            return None
        if entry.get("enabled") is not False:  # missing flag: assume enabled (fail closed)
            names.append(entry["name"])
    return names


class HermesAdapter(AgentAdapter):
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.BaseTransport | None = None,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self._base_url = settings.hermes_base_url
        self._api_key = settings.hermes_api_key.get_secret_value()
        self._model = settings.hermes_model
        self._allowed = frozenset(settings.hermes_allowed_toolsets)
        self._timeout = float(settings.ai_request_timeout_seconds)
        self._max_output = settings.ai_max_output_chars
        self._retries = settings.ai_max_retries
        self._transport = transport
        self._retry_delay = retry_delay_seconds

    def _client(self, timeout: float) -> httpx2.Client:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        return httpx2.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx2.Timeout(timeout, connect=min(timeout, 5.0)),
            trust_env=False,  # never route a local call through a system proxy
            follow_redirects=False,
            transport=self._transport,
        )

    # ------------------------------------------------------------------ health

    def health(self) -> AgentHealth:
        if not self._api_key:
            return AgentHealth(
                AgentState.UNAVAILABLE,
                "HERMES_API_KEY belum diisi (API server Hermes mewajibkan kunci).",
            )
        try:
            with self._client(PROBE_TIMEOUT_SECONDS) as client:
                alive = client.get("/health")
                if alive.status_code != 200:
                    return AgentHealth(
                        AgentState.UNAVAILABLE,
                        f"Hermes menjawab /health dengan HTTP {alive.status_code}.",
                    )
                toolsets = client.get("/v1/toolsets")
        except httpx2.TransportError as exc:
            logger.info("hermes probe failed: %s", type(exc).__name__)
            return AgentHealth(
                AgentState.UNAVAILABLE,
                f"Hermes tidak dapat dihubungi di {self._base_url}. Jalankan `hermes gateway` "
                "dengan profil RABmate.",
            )
        if toolsets.status_code in (401, 403):
            return AgentHealth(AgentState.UNAVAILABLE, "Kunci API Hermes ditolak.")
        if toolsets.status_code != 200:
            return AgentHealth(
                AgentState.UNSAFE,
                "Daftar toolset Hermes tidak dapat dibaca (HTTP "
                f"{toolsets.status_code}); konfigurasi tool tidak dapat diverifikasi.",
            )
        try:
            names = enabled_toolsets(toolsets.json())
        except ValueError:
            names = None
        if names is None:
            return AgentHealth(
                AgentState.UNSAFE, "Format daftar toolset Hermes tidak dikenali; ditolak."
            )
        blocked = sorted(set(names) - self._allowed)
        if blocked:
            return AgentHealth(
                AgentState.UNSAFE,
                "Profil Hermes masih mengaktifkan toolset yang tidak diizinkan: "
                + ", ".join(blocked)
                + ". Nonaktifkan dulu (lihat docs/LOCAL_DEVELOPMENT.md).",
                self._model,
                tuple(names),
            )
        return AgentHealth(AgentState.READY, "Siap.", self._model, tuple(names))

    def _require_ready(self) -> None:
        status = self.health()
        if status.state is AgentState.UNSAFE:
            raise AgentUnsafeConfigError(status.message)
        if status.state is not AgentState.READY:
            raise AgentUnavailableError(status.message)

    # ------------------------------------------------------------------ completion

    def complete(self, request: AgentRequest) -> AgentReply:
        self._require_ready()
        body = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": request.instructions},
                *({"role": m.role, "content": m.content} for m in request.messages),
            ],
        }
        started = time.perf_counter()
        response = self._post_with_retry(body)
        duration_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code in (401, 403):
            raise AgentUnavailableError("Kunci API Hermes ditolak.")
        if response.status_code >= 400:
            logger.warning("hermes completion failed: HTTP %s", response.status_code)
            reason = _error_message(response)
            raise AgentResponseError(
                f"Hermes mengembalikan HTTP {response.status_code}"
                + (f": {reason}" if reason else ".")
            )
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            text = message.get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise AgentResponseError("Format jawaban Hermes tidak dikenali.") from None
        if not isinstance(text, str) or not text.strip():
            raise AgentResponseError("Hermes mengembalikan jawaban kosong.")
        if len(text) > self._max_output:
            raise AgentResponseError("Jawaban AI melebihi batas ukuran yang diizinkan.")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        logger.info("hermes completion ok in %d ms", duration_ms)
        return AgentReply(
            text=text,
            model=payload.get("model") if isinstance(payload.get("model"), str) else self._model,
            duration_ms=duration_ms,
            usage={k: v for k, v in usage.items() if isinstance(v, int)},
        )

    def _post_with_retry(self, body: dict[str, Any]) -> httpx2.Response:
        attempts = self._retries + 1
        for attempt in range(1, attempts + 1):
            try:
                with self._client(self._timeout) as client:
                    response = client.post("/v1/chat/completions", json=body)
            except httpx2.TimeoutException:
                # The full time budget is spent; retrying would double the wait for nothing.
                raise AgentTimeoutError(
                    f"AI lokal tidak menjawab dalam {int(self._timeout)} detik."
                ) from None
            except httpx2.TransportError as exc:
                logger.info("hermes transport error (attempt %d): %s", attempt, type(exc).__name__)
                if attempt < attempts:
                    time.sleep(self._retry_delay)
                    continue
                raise AgentUnavailableError() from None
            if response.status_code in RETRYABLE_STATUS and attempt < attempts:
                logger.info("hermes busy (HTTP %s), retrying", response.status_code)
                time.sleep(self._retry_delay)
                continue
            return response
        raise AgentUnavailableError()  # pragma: no cover - loop always returns or raises


def _error_message(response: httpx2.Response) -> str | None:
    """Hermes' own error text (e.g. a context-window refusal), shortened; never logged."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return None
    message = error.get("message") if isinstance(error, dict) else None
    if not isinstance(message, str) or not message.strip():
        return None
    message = " ".join(message.split()).removeprefix("Internal server error: ")
    return message[:400]


def toolset_names(values: Iterable[str]) -> str:
    return ", ".join(sorted(values)) or "-"
