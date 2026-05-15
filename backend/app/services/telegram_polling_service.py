from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.entities import ChannelConfig, Tenant, WebhookEvent
from app.services.orchestrator import ConversationOrchestrator
from app.services.telegram_adapter import TelegramAdapter
from app.services.tenant_channel_service import TenantChannelService


def _stored_event_id(tenant_id: int, provider_event_id: str) -> str:
    return f"tenant:{tenant_id}:{provider_event_id}"


@dataclass
class TelegramPollResult:
    tenant_id: int
    channel_id: int
    updates_seen: int
    updates_processed: int
    last_update_id: int | None


class TelegramPollingService:
    def __init__(self) -> None:
        self.channel_service = TenantChannelService()
        self.telegram = TelegramAdapter()
        self.orchestrator = ConversationOrchestrator()

    def _active_channels(self, db: Session) -> list[ChannelConfig]:
        rows = db.query(ChannelConfig).filter(ChannelConfig.channel_type == "telegram").all()
        active: list[ChannelConfig] = []
        for row in rows:
            public_config = row.public_config_json or {}
            creds = self.channel_service.credentials(row)
            if public_config.get("enabled") is True and creds.get("bot_token") and creds.get("bot_token") != "pending":
                active.append(row)
        return active

    def _poll_one(self, db: Session, row: ChannelConfig, *, disable_webhook: bool) -> TelegramPollResult:
        public_config = row.public_config_json or {}
        creds = self.channel_service.credentials(row)
        bot_token = str(creds["bot_token"])
        tenant = db.get(Tenant, row.tenant_id)
        if not tenant:
            return TelegramPollResult(tenant_id=row.tenant_id, channel_id=row.id, updates_seen=0, updates_processed=0, last_update_id=None)

        if disable_webhook:
            self.telegram.delete_webhook(bot_token=bot_token, drop_pending_updates=False)

        offset = public_config.get("telegram_poll_offset")
        offset_value = int(offset) if isinstance(offset, int) or (isinstance(offset, str) and offset.isdigit()) else None
        raw = self.telegram.get_updates(bot_token=bot_token, offset=offset_value, timeout_seconds=5)
        updates = raw.get("result") if isinstance(raw, dict) else []
        updates_seen = len(updates) if isinstance(updates, list) else 0
        processed = 0
        last_update_id: int | None = None

        if not isinstance(updates, list):
            return TelegramPollResult(tenant_id=tenant.id, channel_id=row.id, updates_seen=0, updates_processed=0, last_update_id=None)

        for update in updates:
            if not isinstance(update, dict):
                continue
            normalized = self.telegram.normalize_inbound(update)
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                last_update_id = update_id
            if not normalized:
                continue
            stored_event_id = _stored_event_id(tenant.id, normalized.provider_message_id)
            if db.query(WebhookEvent).filter(WebhookEvent.tenant_id == tenant.id, WebhookEvent.provider == "telegram", WebhookEvent.provider_event_id == stored_event_id).first():
                continue
            db.add(
                WebhookEvent(
                    tenant_id=tenant.id,
                    provider="telegram",
                    provider_event_id=stored_event_id,
                    event_type="message",
                    payload_json=normalized.raw,
                )
            )
            db.flush()
            self.orchestrator.handle_inbound(
                db,
                tenant=tenant,
                customer_phone=normalized.customer_address,
                text=normalized.text,
                channel_type="telegram",
                provider_message_id=normalized.provider_message_id,
                payload_json=normalized.raw,
            )
            processed += 1

        if last_update_id is not None:
            public_config["telegram_poll_offset"] = last_update_id + 1
            row.public_config_json = public_config

        return TelegramPollResult(
            tenant_id=tenant.id,
            channel_id=row.id,
            updates_seen=updates_seen,
            updates_processed=processed,
            last_update_id=last_update_id,
        )

    def poll_once(self, db: Session, *, disable_webhook: bool = True) -> list[TelegramPollResult]:
        results: list[TelegramPollResult] = []
        for row in self._active_channels(db):
            results.append(self._poll_one(db, row, disable_webhook=disable_webhook))
        return results
