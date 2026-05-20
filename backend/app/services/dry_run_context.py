from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar


_dry_run_outbound: ContextVar[bool] = ContextVar("dry_run_outbound", default=False)


def dry_run_outbound_enabled() -> bool:
    return _dry_run_outbound.get()


@contextmanager
def dry_run_outbound():
    token = _dry_run_outbound.set(True)
    try:
        yield
    finally:
        _dry_run_outbound.reset(token)
