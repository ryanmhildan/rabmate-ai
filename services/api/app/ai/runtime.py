"""Runtime wiring for AI work: adapter provider, background DB sessions, cached health."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from fastapi import Depends
from sqlalchemy.orm import Session

from app.ai.adapter import AgentAdapter, AgentHealth, AgentState
from app.ai.hermes import HermesAdapter
from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker

HEALTH_CACHE_SECONDS = 30.0

SessionFactory = Callable[[], AbstractContextManager[Session]]


def get_agent_adapter(settings: Settings = Depends(get_settings)) -> AgentAdapter:
    """FastAPI dependency; tests override it with a fake adapter (no model needed)."""
    return HermesAdapter(settings)


@contextmanager
def _background_session() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def get_session_factory() -> SessionFactory:
    """Sessions for background work, which outlives the request's own session."""
    return _background_session


_cache: dict[str, tuple[float, AgentHealth]] = {}
_cache_lock = threading.Lock()


def agent_health(settings: Settings, adapter: AgentAdapter, *, fresh: bool = False) -> AgentHealth:
    if not settings.ai_enabled:
        return AgentHealth(
            AgentState.DISABLED,
            "Asisten AI lokal belum diaktifkan (AI_ENABLED=false). Fitur lain tetap berjalan.",
        )
    key = settings.hermes_base_url
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached and not fresh and now - cached[0] < HEALTH_CACHE_SECONDS:
        return cached[1]
    health = adapter.health()
    with _cache_lock:
        _cache[key] = (now, health)
    return health


def reset_health_cache() -> None:
    with _cache_lock:
        _cache.clear()
