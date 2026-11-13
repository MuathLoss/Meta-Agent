"""Start the single background worker (spec v1.2, T07 and Section 14.1: concurrency 1).

It runs queued jobs and the periodic jobs in app/jobs/periodic.py, so no separate
scheduler container is needed.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from redis import Redis
from rq import Queue, Worker

from app.core.config import settings
from app.jobs.periodic import schedule_all


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    settings.validate_startup()
    # Its own connection without a read timeout: RQ waits on the queue and sets the timeouts it needs.
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.worker_queue_name, connection=connection)
    scheduled = schedule_all(queue)
    logging.getLogger("worker").info("periodic jobs scheduled: %s", ", ".join(scheduled))
    Worker([queue], connection=connection).work(with_scheduler=True, logging_level=settings.log_level)


if __name__ == "__main__":
    main()
