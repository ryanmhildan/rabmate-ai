"""Per-user limit for expensive requests: rendering PDFs/XLSX, issuing documents, uploads and
imports, and AI requests (ADR-046).

A sliding window kept in process memory: enough for the single-process MVP. Behind several API
workers each worker counts on its own (the effective limit multiplies); put a shared limiter (for
example at the reverse proxy) in front before scaling out. Login throttling is separate and
persistent (login_attempts table).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import Depends

from app.api.deps import RequestContext, get_context
from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError

WINDOW_SECONDS = 60.0


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, *, now: float | None = None) -> float | None:
        """Counts one request; returns the seconds to wait when `key` is over `limit`."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return max(hits[0] + WINDOW_SECONDS - now, 0.0)
            hits.append(now)
            if len(self._hits) > 10_000:  # forget idle keys so memory stays bounded
                for stale in [k for k, v in self._hits.items() if not v or v[-1] <= now - 60]:
                    del self._hits[stale]
            return None

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


expensive_window = SlidingWindow()


def limit_expensive(
    ctx: RequestContext = Depends(get_context),
    settings: Settings = Depends(get_settings),
) -> None:
    """Dependency for endpoints that render, store files or call the local model."""
    limit = settings.rate_limit_expensive_per_minute
    if limit == 0:
        return
    wait = expensive_window.hit(f"{ctx.organization_id}:{ctx.user_id}", limit)
    if wait is not None:
        seconds = max(1, math.ceil(wait))
        raise RateLimitedError(
            f"Terlalu banyak permintaan berat dalam satu menit. Coba lagi dalam {seconds} detik.",
            headers={"Retry-After": str(seconds)},
        )


# For route decorators: `@router.post(..., dependencies=EXPENSIVE)`.
EXPENSIVE = [Depends(limit_expensive)]
