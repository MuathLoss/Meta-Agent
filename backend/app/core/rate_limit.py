from __future__ import annotations

from collections import defaultdict, deque
from hashlib import sha256
from time import monotonic

from fastapi import HTTPException, Request

RATE_LIMIT_DETAIL = "Too many requests. Please try again later."


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        self._hits.clear()

    def check(self, key: str, *, max_requests: int, window_seconds: int) -> None:
        now = monotonic()
        cutoff = now - window_seconds
        hits = self._hits[key]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= max_requests:
            raise HTTPException(status_code=429, detail=RATE_LIMIT_DETAIL)
        hits.append(now)
        self._cleanup(cutoff)

    def _cleanup(self, cutoff: float) -> None:
        stale_keys = []
        for key, hits in self._hits.items():
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                stale_keys.append(key)
        for key in stale_keys:
            self._hits.pop(key, None)


rate_limiter = InMemoryRateLimiter()


def reset_rate_limits() -> None:
    rate_limiter.reset()


def client_ip(request: Request | None) -> str:
    client = getattr(request, "client", None)
    if client is None or not getattr(client, "host", None):
        return "local"
    return client.host


def normalized_identifier(value: object) -> str:
    text = str(value or "").strip().lower()
    return sha256(text.encode("utf-8")).hexdigest() if text else "blank"


def enforce_rate_limit(key: str, *, max_requests: int, window_seconds: int) -> None:
    rate_limiter.check(key, max_requests=max_requests, window_seconds=window_seconds)
