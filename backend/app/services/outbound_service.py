from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from app.core.redaction import redact_sensitive
from app.models.entities import ChannelConfig, Message
from app.services.tenant_channel_service import TenantChannelService
from app.services.telegram_adapter import TelegramAdapter
from app.services.whatsapp_adapter import WhatsAppAdapter


@dataclass
class OutboundDispatchResult:
    channel_type: str
    send_status: str
    provider_message_id: str | None
    provider_response: dict | None
    error: str | None = None


class OutboundService:
    def __init__(self) -> None:
        self.channel_service = TenantChannelService()
        self.whatsapp = WhatsAppAdapter()
        self.telegram = TelegramAdapter()

    def supports_channel(self, channel_type: str) -> bool:
        return channel_type in {"whatsapp", "telegram"}

    def channel_ready(self, channel: ChannelConfig) -> tuple[bool, str | None]:
        if not self.supports_channel(channel.channel_type):
            return False, "unsupported_channel"

        public_config = channel.public_config_json or {}
        if public_config.get("enabled") is False:
            return False, "channel_disabled"
        if public_config.get("live_send_enabled") is not True:
            return False, "live_send_not_enabled"
        if channel.status not in {"configured", "connected", "active"}:
            return False, f"channel_status_{channel.status}"

        creds = self.channel_service.credentials(channel)
        if channel.channel_type == "whatsapp":
            token = creds.get("access_token")
            phone_number_id = creds.get("phone_number_id") or public_config.get("phone_number_id")
            if not token or token == "pending" or not phone_number_id:
                return False, "missing_whatsapp_credentials"
            return True, None

        if channel.channel_type == "telegram":
            bot_token = creds.get("bot_token")
            if not bot_token or bot_token == "pending":
                return False, "missing_telegram_credentials"
            return True, None

        return False, "unsupported_channel"

    def resolve_send_channel(self, db: Session, *, tenant_id: int, preferred_channel_type: str | None = None) -> ChannelConfig | None:
        rows = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant_id).all()
        by_type = {row.channel_type: row for row in rows}

        ordered: list[str] = []
        preferred = (preferred_channel_type or "").strip().lower()
        if preferred and preferred != "auto":
            ordered.append(preferred)
        for fallback in ["whatsapp", "telegram"]:
            if fallback not in ordered:
                ordered.append(fallback)
        for channel_type in sorted(by_type):
            if channel_type not in ordered:
                ordered.append(channel_type)

        for channel_type in ordered:
            row = by_type.get(channel_type)
            if not row:
                continue
            ready, _ = self.channel_ready(row)
            if ready:
                return row
        return None

    def is_unreachable_recipient_failure(self, *, channel_type: str, payload_json: dict | None) -> bool:
        payload = payload_json or {}
        if channel_type != "telegram":
            return False
        if str(payload.get("send_status")) != "send_failed":
            return False
        if payload.get("error_type") == "recipient_unreachable":
            return True
        error = str(payload.get("error") or "").lower()
        return any(fragment in error for fragment in [
            "chat not found",
            "bot was blocked by the user",
            "user is deactivated",
            "forbidden",
            "have no rights to send a message",
        ])

    def success_payload(self, dispatched: OutboundDispatchResult) -> dict:
        payload = {
            "send_status": dispatched.send_status,
            "provider": dispatched.channel_type,
            "channel_type": dispatched.channel_type,
        }
        if dispatched.provider_message_id:
            payload["provider_message_id"] = dispatched.provider_message_id
        return payload

    def failure_payload(self, *, channel_type: str, exc: Exception) -> dict:
        error_type = "provider_send_error"
        safe_error_code: str | None = None
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(exc, httpx.TimeoutException):
            error_type = "provider_timeout"
        elif isinstance(exc, httpx.NetworkError):
            error_type = "provider_network_error"
        elif status_code is not None:
            safe_error_code = f"http_{status_code}"
            if status_code == 429:
                error_type = "provider_rate_limited"
            elif status_code in {401, 403}:
                error_type = "provider_auth_or_permission_error"
            elif 400 <= int(status_code) < 500:
                error_type = "provider_rejected_request"
            else:
                error_type = "provider_http_error"

        lowered = str(exc).lower()
        if channel_type == "telegram" and any(fragment in lowered for fragment in [
            "chat not found",
            "bot was blocked by the user",
            "user is deactivated",
            "forbidden",
            "have no rights to send a message",
        ]):
            error_type = "recipient_unreachable"

        payload = {
            "send_status": "send_failed",
            "provider": channel_type,
            "channel_type": channel_type,
            "error_type": error_type,
        }
        if safe_error_code:
            payload["safe_error_code"] = safe_error_code
        return payload

    def dispatch_via_channel(self, *, channel: ChannelConfig, destination: str, text: str) -> OutboundDispatchResult:
        public_config = channel.public_config_json or {}
        creds = self.channel_service.credentials(channel)

        if channel.channel_type == "whatsapp":
            result = self.whatsapp.send_text(
                access_token=creds["access_token"],
                phone_number_id=creds.get("phone_number_id") or public_config.get("phone_number_id"),
                to_phone=destination,
                text=text,
            )
            provider_id = None
            messages = result.get("messages") if isinstance(result, dict) else None
            if isinstance(messages, list) and messages:
                provider_id = messages[0].get("id")
            return OutboundDispatchResult(
                channel_type=channel.channel_type,
                send_status="sent",
                provider_message_id=str(provider_id) if provider_id else None,
                provider_response=result if isinstance(result, dict) else None,
            )

        if channel.channel_type == "telegram":
            result = self.telegram.send_text(bot_token=creds["bot_token"], chat_id=destination, text=text)
            provider_id = result.get("result", {}).get("message_id") if isinstance(result, dict) else None
            return OutboundDispatchResult(
                channel_type=channel.channel_type,
                send_status="sent",
                provider_message_id=str(provider_id) if provider_id is not None else None,
                provider_response=result if isinstance(result, dict) else None,
            )

        return OutboundDispatchResult(
            channel_type=channel.channel_type,
            send_status="no_adapter",
            provider_message_id=None,
            provider_response=None,
            error="unsupported_channel",
        )

    def store_local_outbound(self, db: Session, *, tenant_id: int, conversation_id: int, text: str, intent_code: str | None, payload_json: dict | None = None) -> Message:
        row = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            provider_message_id=f"local-{uuid4()}",
            text=text,
            payload_json=redact_sensitive(payload_json or {"send_status": "local_preview"}),
            intent_code=intent_code,
        )
        db.add(row)
        db.flush()
        return row

    def send_or_store(self, db: Session, *, tenant_id: int, conversation_id: int, channel_type: str, destination: str, text: str, intent_code: str | None) -> Message:
        channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel_type == channel_type).first()
        if not channel:
            return self.store_local_outbound(db, tenant_id=tenant_id, conversation_id=conversation_id, text=text, intent_code=intent_code, payload_json={"send_status": "no_adapter", "provider": channel_type, "channel_type": channel_type})

        ready, reason = self.channel_ready(channel)
        if not ready:
            return self.store_local_outbound(
                db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                text=text,
                intent_code=intent_code,
                payload_json={"send_status": "stored_only", "reason": reason, "provider": channel_type, "channel_type": channel_type},
            )

        try:
            dispatched = self.dispatch_via_channel(channel=channel, destination=destination, text=text)
            row = Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                direction="outbound",
                provider_message_id=dispatched.provider_message_id or f"local-{uuid4()}",
                text=text,
                payload_json=redact_sensitive(self.success_payload(dispatched)),
                intent_code=intent_code,
            )
            db.add(row)
            db.flush()
            return row
        except Exception as exc:
            return self.store_local_outbound(db, tenant_id=tenant_id, conversation_id=conversation_id, text=text, intent_code=intent_code, payload_json=self.failure_payload(channel_type=channel_type, exc=exc))

        return self.store_local_outbound(db, tenant_id=tenant_id, conversation_id=conversation_id, text=text, intent_code=intent_code, payload_json={"send_status": "no_adapter", "provider": channel_type, "channel_type": channel_type})
