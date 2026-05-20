from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.entities import ChannelConfig, Tenant
from app.services.email_adapter import EmailAdapter
from app.services.email_polling_service import EmailPollResult, EmailPollingService
from app.services.tenant_channel_service import TenantChannelService

logger = logging.getLogger(__name__)
ACTIVE_CHANNEL_STATUSES = {"configured", "connected", "active"}


@dataclass
class EmailPollingRunSummary:
    channels_seen: int = 0
    channels_polled: int = 0
    channels_skipped: int = 0
    messages_seen: int = 0
    messages_processed: int = 0
    errors: int = 0


class EmailPollingScheduler:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        polling_service: EmailPollingService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.polling_service = polling_service or EmailPollingService()
        self.channel_service = TenantChannelService()
        self.email = EmailAdapter()

    def _is_ready_for_automatic_polling(self, row: ChannelConfig) -> tuple[bool, str | None]:
        public_config = row.public_config_json or {}
        if public_config.get("enabled") is not True:
            return False, "channel_disabled"
        if public_config.get("live_send_enabled") is not True:
            return False, "live_send_not_enabled"
        if row.status not in ACTIVE_CHANNEL_STATUSES:
            return False, f"channel_status_{row.status}"
        credentials = self.channel_service.credentials(row)
        return self.email.imap_ready(credentials)

    def run_once(self) -> EmailPollingRunSummary:
        summary = EmailPollingRunSummary()
        with self.session_factory() as db:
            rows = (
                db.query(ChannelConfig)
                .join(Tenant, Tenant.id == ChannelConfig.tenant_id)
                .filter(ChannelConfig.channel_type == "email", Tenant.status == "active")
                .all()
            )
            summary.channels_seen = len(rows)
            for row in rows:
                try:
                    ready, reason = self._is_ready_for_automatic_polling(row)
                    if not ready:
                        summary.channels_skipped += 1
                        logger.info(
                            "email polling skipped",
                            extra={"tenant_id": row.tenant_id, "channel_id": row.id, "reason": reason},
                        )
                        continue

                    result: EmailPollResult = self.polling_service.poll_channel(db, row)
                    db.commit()
                    summary.channels_polled += 1
                    summary.messages_seen += result.messages_seen
                    summary.messages_processed += result.messages_processed
                    if result.error:
                        summary.errors += 1
                        logger.warning(
                            "email polling returned error",
                            extra={"tenant_id": row.tenant_id, "channel_id": row.id, "error": result.error},
                        )
                except Exception as exc:
                    db.rollback()
                    summary.errors += 1
                    logger.warning(
                        "email polling channel failed",
                        extra={"tenant_id": row.tenant_id, "channel_id": row.id, "error_type": type(exc).__name__},
                    )
        logger.info(
            "email polling run complete",
            extra={
                "channels_seen": summary.channels_seen,
                "channels_polled": summary.channels_polled,
                "channels_skipped": summary.channels_skipped,
                "messages_seen": summary.messages_seen,
                "messages_processed": summary.messages_processed,
                "errors": summary.errors,
            },
        )
        return summary


class EmailPollingBackgroundTask:
    def __init__(
        self,
        *,
        scheduler: EmailPollingScheduler | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self.scheduler = scheduler or EmailPollingScheduler()
        self.interval_seconds = max(int(interval_seconds if interval_seconds is not None else settings.email_poll_interval_seconds), 5)
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    async def _run_loop(self) -> None:
        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.scheduler.run_once)
            except Exception as exc:
                logger.warning("email polling loop failed", extra={"error_type": type(exc).__name__})
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            await self._task
