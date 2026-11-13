"""Periodic jobs that run inside the single RQ worker (spec v1.2: no separate scheduler container).

Each periodic job is scheduled for the next whole multiple of its interval, with a job id
built from that time. Scheduling the same slot twice (worker restart, two workers) reuses
the same id, so the slot still runs once. After a run, the job schedules its next slot.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from typing import Callable

from rq import Queue

from app.core.config import settings
from app.jobs.queue import get_queue, get_redis

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "worker:heartbeat"
# Keep a finished periodic run around briefly for debugging; keep failures for a day.
RESULT_TTL_SECONDS = 300
FAILURE_TTL_SECONDS = 86400


@dataclass(frozen=True)
class PeriodicJob:
    name: str
    interval_seconds: int
    target: str  # dotted path to a function that takes no arguments


def periodic_jobs() -> tuple[PeriodicJob, ...]:
    # Later phases add retention cleanup, usage reconciliation and alerts here.
    return (PeriodicJob("heartbeat", max(settings.worker_heartbeat_seconds, 10), "app.jobs.periodic.heartbeat"),)


def next_slot(interval_seconds: int, now: float) -> int:
    return (int(now) // interval_seconds + 1) * interval_seconds


def slot_job_id(job: PeriodicJob, slot: int) -> str:
    # RQ job ids allow only letters, digits, underscores and dashes.
    return f"periodic-{job.name}-{slot}"


def schedule_next(job: PeriodicJob, queue: Queue | None = None, now: float | None = None) -> str:
    queue = queue or get_queue()
    slot = next_slot(job.interval_seconds, time.time() if now is None else now)
    job_id = slot_job_id(job, slot)
    queue.enqueue_at(
        datetime.fromtimestamp(slot, tz=timezone.utc),
        run_periodic,
        job.name,
        job_id=job_id,
        result_ttl=RESULT_TTL_SECONDS,
        failure_ttl=FAILURE_TTL_SECONDS,
        description=f"periodic:{job.name}",
    )
    return job_id


def schedule_all(queue: Queue | None = None) -> list[str]:
    return [schedule_next(job, queue) for job in periodic_jobs()]


def _resolve(target: str) -> Callable[[], object]:
    module_name, _, attribute = target.rpartition(".")
    return getattr(import_module(module_name), attribute)


def run_periodic(name: str) -> object:
    job = next((item for item in periodic_jobs() if item.name == name), None)
    if job is None:
        logger.warning("unknown periodic job skipped", extra={"job": name})
        return None
    try:
        return _resolve(job.target)()
    finally:
        # Always book the next slot, even when this run failed.
        schedule_next(job)


def heartbeat() -> int:
    """Record that the worker is alive; /health/ready reports it."""
    stamp = int(time.time())
    get_redis().set(HEARTBEAT_KEY, stamp, ex=max(settings.worker_heartbeat_seconds, 10) * 3)
    return stamp


def worker_heartbeat_age_seconds() -> int | None:
    try:
        raw = get_redis().get(HEARTBEAT_KEY)
    except Exception:
        return None
    if raw is None:
        return None
    return max(int(time.time()) - int(raw), 0)
