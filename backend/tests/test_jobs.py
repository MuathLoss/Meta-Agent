"""Background worker (spec v1.2, T07). The Redis cases run when REDIS_TEST_URL is set (CI and
the Docker test command in docs/operations.md); the rest run everywhere."""
import os
from uuid import uuid4

import pytest
from redis import Redis
from rq import Queue, SimpleWorker
from rq.registry import ScheduledJobRegistry

from app.core.config import settings
from app.jobs import periodic
from app.jobs.periodic import PeriodicJob, next_slot, slot_job_id

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL")
needs_redis = pytest.mark.skipif(not REDIS_TEST_URL, reason="REDIS_TEST_URL not set")


def test_next_slot_is_the_next_whole_interval():
    assert next_slot(60, 120) == 180
    assert next_slot(60, 179.9) == 180
    assert next_slot(60, 180) == 240


def test_slot_job_id_names_the_job_and_slot():
    assert slot_job_id(PeriodicJob("heartbeat", 60, "x.y"), 180) == "periodic-heartbeat-180"


def test_only_known_periodic_jobs_are_registered():
    names = [job.name for job in periodic.periodic_jobs()]
    assert names == ["heartbeat"]
    assert all(job.interval_seconds >= 10 for job in periodic.periodic_jobs())


@pytest.fixture()
def redis_queue(monkeypatch):
    connection = Redis.from_url(REDIS_TEST_URL)
    name = f"test-{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "redis_url", REDIS_TEST_URL)
    monkeypatch.setattr(settings, "worker_queue_name", name)
    queue = Queue(name, connection=connection)
    yield queue
    queue.empty()
    for key in connection.scan_iter(f"rq:*{name}*"):
        connection.delete(key)


@needs_redis
def test_scheduling_the_same_slot_twice_runs_it_once(redis_queue):
    job = periodic.periodic_jobs()[0]
    first = periodic.schedule_next(job, redis_queue, now=1_000)
    second = periodic.schedule_next(job, redis_queue, now=1_001)
    assert first == second
    registry = ScheduledJobRegistry(queue=redis_queue)
    assert registry.get_job_ids() == [first]


@needs_redis
def test_worker_runs_a_periodic_job_and_books_the_next_slot(redis_queue):
    redis_queue.connection.delete(periodic.HEARTBEAT_KEY)
    redis_queue.enqueue(periodic.run_periodic, "heartbeat")
    SimpleWorker([redis_queue], connection=redis_queue.connection).work(burst=True)
    assert periodic.worker_heartbeat_age_seconds() is not None
    upcoming = ScheduledJobRegistry(queue=redis_queue).get_job_ids()
    assert len(upcoming) == 1 and upcoming[0].startswith("periodic-heartbeat-")
