"""The narrow seam between RABmate and an agent runtime (ADR-002, ADR-040).

Business code only sees `AgentAdapter`: it sends instructions + messages and receives text.
Which runtime sits behind it (Hermes Agent's API server today) can change without touching the
workflows. Errors carry a stable code and a message that is safe to show to users — never prompt
or document content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol


class AgentState(StrEnum):
    DISABLED = "disabled"  # AI_ENABLED=false
    READY = "ready"
    UNAVAILABLE = "unavailable"  # not running, unreachable, wrong key, missing endpoint
    UNSAFE = "unsafe"  # reachable, but the profile has tools enabled that RABmate does not allow


@dataclass(frozen=True)
class AgentHealth:
    state: AgentState
    message: str
    model: str | None = None
    toolsets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class AgentRequest:
    instructions: str
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class AgentReply:
    text: str
    model: str | None
    duration_ms: int
    usage: dict[str, int] = field(default_factory=dict)


class AgentError(Exception):
    code = "ai_error"
    message = "Asisten AI gagal memproses permintaan."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class AgentDisabledError(AgentError):
    code = "ai_disabled"
    message = "Asisten AI lokal belum diaktifkan. Fitur lain tetap dapat digunakan."


class AgentUnavailableError(AgentError):
    code = "ai_unavailable"
    message = "AI lokal (Hermes) tidak dapat dihubungi."


class AgentUnsafeConfigError(AgentError):
    code = "ai_unsafe_config"
    message = "Konfigurasi Hermes tidak aman untuk RABmate."


class AgentTimeoutError(AgentError):
    code = "ai_timeout"
    message = "AI lokal tidak menjawab dalam batas waktu."


class AgentResponseError(AgentError):
    code = "ai_bad_response"
    message = "Jawaban AI lokal tidak dapat dipakai."


class AgentAdapter(Protocol):
    def health(self) -> AgentHealth: ...

    def complete(self, request: AgentRequest) -> AgentReply: ...
