"""HermesAdapter against a fake transport: no Hermes or model needed (ADR-040)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.adapter import (
    AgentRequest,
    AgentResponseError,
    AgentState,
    AgentTimeoutError,
    AgentUnavailableError,
    AgentUnsafeConfigError,
    Message,
)
from app.ai.hermes import HermesAdapter, enabled_toolsets
from app.core.config import Settings

Handler = Callable[[httpx2.Request], httpx2.Response]
REQUEST = AgentRequest("Instruksi sistem", (Message("user", "Halo"),))


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ai_enabled": True,
        "hermes_api_key": SecretStr("kunci-uji"),
        "hermes_model": "rabmate",
        "ai_request_timeout_seconds": 30,
        "ai_max_retries": 1,
        **overrides,
    }
    return Settings(**values)


class FakeHermes:
    """Routes like Hermes' API server; records every request it receives."""

    def __init__(self, *, toolsets: Any = None, completions: list[httpx2.Response] | None = None):
        self.toolsets = {"toolsets": []} if toolsets is None else toolsets
        self.completions = completions or [reply("{}")]
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path == "/health":
            return httpx2.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/toolsets":
            if request.headers.get("authorization") != "Bearer kunci-uji":
                return httpx2.Response(401, json={"error": "unauthorized"})
            if isinstance(self.toolsets, httpx2.Response):
                return self.toolsets
            return httpx2.Response(200, json=self.toolsets)
        if request.url.path == "/v1/chat/completions":
            return self.completions.pop(0)
        return httpx2.Response(404)

    def adapter(self, **overrides: Any) -> HermesAdapter:
        return HermesAdapter(
            settings(**overrides), transport=httpx2.MockTransport(self), retry_delay_seconds=0
        )

    @property
    def completion_calls(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == "/v1/chat/completions"]


def reply(content: str, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": "rabmate",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


# --------------------------------------------------------------------------- configuration


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://192.168.1.5:8642",
        "http://hermes.example.com:8642",
        "http://0.0.0.0:8642",
        "ftp://127.0.0.1:8642",
    ],
)
def test_only_loopback_hermes_urls_are_accepted(url: str) -> None:
    with pytest.raises(ValidationError, match="HERMES_BASE_URL"):
        settings(hermes_base_url=url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8642", "http://localhost:8642/", "http://[::1]:8642"]
)
def test_loopback_urls_are_accepted(url: str) -> None:
    assert settings(hermes_base_url=url).hermes_base_url == url.rstrip("/")


# --------------------------------------------------------------------------- health


def test_ready_when_reachable_keyed_and_no_tools_enabled() -> None:
    hermes = FakeHermes(toolsets={"toolsets": [{"name": "terminal", "enabled": False}]})
    health = hermes.adapter().health()
    assert health.state is AgentState.READY
    assert health.model == "rabmate"


def test_missing_key_is_reported_without_calling_hermes() -> None:
    hermes = FakeHermes()
    health = hermes.adapter(hermes_api_key=SecretStr("")).health()
    assert health.state is AgentState.UNAVAILABLE
    assert "HERMES_API_KEY" in health.message
    assert hermes.requests == []


def test_unreachable_hermes_is_unavailable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    adapter = HermesAdapter(settings(), transport=httpx2.MockTransport(refuse))
    health = adapter.health()
    assert health.state is AgentState.UNAVAILABLE
    assert "tidak dapat dihubungi" in health.message


@pytest.mark.parametrize(
    ("toolsets", "blocked"),
    [
        ({"toolsets": [{"name": "terminal", "enabled": True}]}, "terminal"),
        ([{"name": "file", "enabled": True}, {"name": "web", "enabled": True}], "file, web"),
        ({"toolsets": [{"name": "memory"}]}, "memory"),  # no flag: assumed enabled
        ({"toolsets": [{"name": "mcp-rabmate", "enabled": True}]}, "mcp-rabmate"),
    ],
)
def test_enabled_toolsets_outside_the_allowlist_are_unsafe(toolsets: Any, blocked: str) -> None:
    health = FakeHermes(toolsets=toolsets).adapter().health()
    assert health.state is AgentState.UNSAFE
    assert blocked in health.message


def test_allowlisted_toolset_is_accepted() -> None:
    hermes = FakeHermes(toolsets={"toolsets": [{"name": "mcp-rabmate", "enabled": True}]})
    health = hermes.adapter(hermes_allowed_toolsets=["mcp-rabmate"]).health()
    assert health.state is AgentState.READY
    assert health.toolsets == ("mcp-rabmate",)


@pytest.mark.parametrize(
    "toolsets", [httpx2.Response(404), {"unexpected": True}, [{"enabled": True}], "oops"]
)
def test_unverifiable_toolsets_fail_closed(toolsets: Any) -> None:
    assert FakeHermes(toolsets=toolsets).adapter().health().state is AgentState.UNSAFE


def test_wrong_key_is_unavailable() -> None:
    health = FakeHermes().adapter(hermes_api_key=SecretStr("salah")).health()
    assert health.state is AgentState.UNAVAILABLE
    assert "ditolak" in health.message


def test_enabled_toolsets_parser() -> None:
    assert enabled_toolsets({"data": [{"name": "a", "enabled": False}, {"name": "b"}]}) == ["b"]
    assert enabled_toolsets({"toolsets": "x"}) is None


# --------------------------------------------------------------------------- completion


def test_completion_sends_system_and_user_messages_to_the_profile_model() -> None:
    hermes = FakeHermes(completions=[reply('{"items": []}')])
    result = hermes.adapter().complete(REQUEST)
    assert result.text == '{"items": []}'
    assert result.model == "rabmate"
    (call,) = hermes.completion_calls
    body = json.loads(call.content)
    assert body["model"] == "rabmate"
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "Instruksi sistem"},
        {"role": "user", "content": "Halo"},
    ]
    assert call.headers["authorization"] == "Bearer kunci-uji"
    # Only the configured local server is ever contacted — there is no other provider.
    assert {(r.url.host, r.url.port) for r in hermes.requests} == {("127.0.0.1", 8642)}


def test_unsafe_profile_is_never_sent_a_prompt() -> None:
    hermes = FakeHermes(toolsets={"toolsets": [{"name": "terminal", "enabled": True}]})
    with pytest.raises(AgentUnsafeConfigError, match="terminal"):
        hermes.adapter().complete(REQUEST)
    assert hermes.completion_calls == []


def test_busy_server_is_retried_once_then_reported() -> None:
    hermes = FakeHermes(completions=[httpx2.Response(503), reply("ok")])
    assert hermes.adapter().complete(REQUEST).text == "ok"
    assert len(hermes.completion_calls) == 2

    hermes = FakeHermes(completions=[httpx2.Response(503), httpx2.Response(503)])
    with pytest.raises(AgentResponseError, match="HTTP 503"):
        hermes.adapter().complete(REQUEST)
    assert len(hermes.completion_calls) == 2

    hermes = FakeHermes(completions=[httpx2.Response(503)])
    with pytest.raises(AgentResponseError):
        hermes.adapter(ai_max_retries=0).complete(REQUEST)
    assert len(hermes.completion_calls) == 1


def test_timeout_is_not_retried() -> None:
    calls: list[str] = []

    def slow(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/v1/chat/completions":
            calls.append("x")
            raise httpx2.ReadTimeout("timed out", request=request)
        return FakeHermes()(request)

    adapter = HermesAdapter(settings(), transport=httpx2.MockTransport(slow), retry_delay_seconds=0)
    with pytest.raises(AgentTimeoutError, match="30 detik"):
        adapter.complete(REQUEST)
    assert calls == ["x"]


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, json={"choices": []}),
        httpx2.Response(200, content=b"not json"),
        reply("   "),
        httpx2.Response(500, json={"error": "boom"}),
    ],
)
def test_unusable_replies_raise_response_errors(response: httpx2.Response) -> None:
    with pytest.raises(AgentResponseError):
        FakeHermes(completions=[response]).adapter(ai_max_retries=0).complete(REQUEST)


def test_hermes_error_text_is_passed_on_shortened() -> None:
    refusal = (
        "Internal server error: Model qwen2.5:3b has a context window of 32,768 tokens, "
        "which is below the minimum 64,000 required by Hermes Agent." + " x" * 400
    )
    hermes = FakeHermes(completions=[httpx2.Response(500, json={"error": {"message": refusal}})])
    with pytest.raises(AgentResponseError) as caught:
        hermes.adapter(ai_max_retries=0).complete(REQUEST)
    message = caught.value.message
    assert message.startswith(
        "Hermes mengembalikan HTTP 500: Model qwen2.5:3b has a context window"
    )
    assert len(message) < 450


def test_oversized_reply_is_rejected() -> None:
    hermes = FakeHermes(completions=[reply("x" * 2000)])
    with pytest.raises(AgentResponseError, match="batas ukuran"):
        hermes.adapter(ai_max_output_chars=1000).complete(REQUEST)


def test_rejected_key_during_completion_is_unavailable() -> None:
    hermes = FakeHermes(completions=[httpx2.Response(401)])
    with pytest.raises(AgentUnavailableError, match="ditolak"):
        hermes.adapter().complete(REQUEST)
