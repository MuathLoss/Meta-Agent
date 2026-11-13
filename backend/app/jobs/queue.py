from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue

from app.core.config import settings

# Short connect timeout: a missing Redis must not hang API requests or health checks.
CONNECT_TIMEOUT_SECONDS = 2
# The worker blocks on the queue for longer than this, so RQ sets its own read timeout there.
SOCKET_TIMEOUT_SECONDS = 5


@lru_cache(maxsize=4)
def _redis_for(url: str) -> Redis:
    return Redis.from_url(url, socket_connect_timeout=CONNECT_TIMEOUT_SECONDS, socket_timeout=SOCKET_TIMEOUT_SECONDS)


def get_redis() -> Redis:
    return _redis_for(settings.redis_url)


def get_queue(name: str | None = None) -> Queue:
    return Queue(name or settings.worker_queue_name, connection=get_redis())


def redis_reachable() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False
