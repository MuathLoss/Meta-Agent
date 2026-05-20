from __future__ import annotations

import email
import imaplib
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from email.policy import default
from email.utils import parseaddr
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import ChannelConfig, Tenant, WebhookEvent
from app.services.email_adapter import EmailAdapter
from app.services.orchestrator import ConversationOrchestrator
from app.services.tenant_channel_service import TenantChannelService


def _stored_event_id(tenant_id: int, provider_event_id: str) -> str:
    return f"tenant:{tenant_id}:{provider_event_id}"


@dataclass
class EmailPollResult:
    tenant_id: int
    channel_id: int
    messages_seen: int
    messages_processed: int
    error: str | None = None


@dataclass
class NormalizedEmailMessage:
    provider_message_id: str
    from_email: str
    from_name: str | None
    subject: str | None
    text: str
    references: str | None
    raw: dict[str, Any]


class EmailPollingService:
    def __init__(self) -> None:
        self.channel_service = TenantChannelService()
        self.email = EmailAdapter()
        self.orchestrator = ConversationOrchestrator()

    def _bool_value(self, value: object, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _decode_header_value(self, value: object) -> str:
        try:
            return str(make_header(decode_header(str(value or "")))).strip()
        except Exception:
            return str(value or "").strip()

    def _text_body(self, msg: Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition") or "").lower()
                if content_type != "text/plain" or "attachment" in disposition:
                    continue
                try:
                    return part.get_content().strip()
                except Exception:
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace").strip()
        try:
            return msg.get_content().strip()
        except Exception:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
        return ""

    def normalize_message(self, raw_bytes: bytes, *, fallback_uid: str) -> NormalizedEmailMessage | None:
        try:
            msg = email.message_from_bytes(raw_bytes, policy=default)
        except Exception:
            return None
        from_name, from_email = parseaddr(str(msg.get("From") or ""))
        from_email = from_email.strip().lower()
        text = self._text_body(msg)
        if not from_email or not text:
            return None
        subject = self._decode_header_value(msg.get("Subject"))
        message_id = str(msg.get("Message-ID") or "").strip() or f"imap-{fallback_uid}"
        references = str(msg.get("References") or msg.get("In-Reply-To") or "").strip() or None
        safe_subject = subject[:255] if subject else None
        return NormalizedEmailMessage(
            provider_message_id=message_id[:255],
            from_email=from_email,
            from_name=self._decode_header_value(from_name)[:120] if from_name else None,
            subject=safe_subject,
            text=text[:12000],
            references=references[:500] if references else None,
            raw={
                "source": "email_imap",
                "from_email": from_email,
                "from_name_provided": bool(from_name),
                "subject_provided": bool(safe_subject),
                "message_id": message_id[:255],
                "references_provided": bool(references),
            },
        )

    def _connect(self, credentials: dict[str, Any]):
        host = str(credentials["imap_host"]).strip()
        port = int(str(credentials["imap_port"]).strip())
        use_ssl = self._bool_value(credentials.get("imap_use_ssl"), default=True)
        client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
        client.login(str(credentials["imap_username"]).strip(), str(credentials["imap_password"]))
        return client

    def poll_channel(self, db: Session, channel: ChannelConfig) -> EmailPollResult:
        public_config = channel.public_config_json or {}
        if public_config.get("enabled") is False:
            return EmailPollResult(channel.tenant_id, channel.id, 0, 0, "channel_disabled")
        if channel.status not in {"configured", "connected", "active"}:
            return EmailPollResult(channel.tenant_id, channel.id, 0, 0, f"channel_status_{channel.status}")
        tenant = db.get(Tenant, channel.tenant_id)
        if not tenant:
            return EmailPollResult(channel.tenant_id, channel.id, 0, 0, "tenant_not_found")

        credentials = self.channel_service.credentials(channel)
        ready, reason = self.email.imap_ready(credentials)
        if not ready:
            return EmailPollResult(tenant.id, channel.id, 0, 0, reason)

        mailbox = str(credentials.get("imap_mailbox") or "INBOX").strip() or "INBOX"
        messages_seen = 0
        messages_processed = 0
        client = self._connect(credentials)
        try:
            status, _ = client.select(mailbox)
            if status != "OK":
                return EmailPollResult(tenant.id, channel.id, 0, 0, "imap_select_failed")
            status, search_data = client.search(None, "UNSEEN")
            if status != "OK" or not search_data:
                return EmailPollResult(tenant.id, channel.id, 0, 0, "imap_search_failed")
            ids = search_data[0].split()
            messages_seen = len(ids)
            for uid in ids:
                uid_text = uid.decode("utf-8", errors="replace") if isinstance(uid, bytes) else str(uid)
                status, fetch_data = client.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue
                raw_bytes = None
                for item in fetch_data or []:
                    if isinstance(item, tuple) and isinstance(item[1], bytes):
                        raw_bytes = item[1]
                        break
                if raw_bytes is None:
                    continue
                normalized = self.normalize_message(raw_bytes, fallback_uid=uid_text)
                if not normalized:
                    continue
                stored_event_id = _stored_event_id(tenant.id, normalized.provider_message_id)
                if db.query(WebhookEvent).filter(WebhookEvent.tenant_id == tenant.id, WebhookEvent.provider == "email", WebhookEvent.provider_event_id == stored_event_id).first():
                    client.store(uid, "+FLAGS", "\\Seen")
                    continue
                db.add(
                    WebhookEvent(
                        tenant_id=tenant.id,
                        provider="email",
                        provider_event_id=stored_event_id,
                        event_type="message",
                        payload_json=normalized.raw,
                    )
                )
                db.flush()
                decision = self.orchestrator.handle_inbound(
                    db,
                    tenant=tenant,
                    customer_phone=normalized.from_email,
                    text=normalized.text,
                    channel_type="email",
                    provider_message_id=normalized.provider_message_id,
                    payload_json=normalized.raw,
                )
                customer = self.orchestrator.customer_identity.lookup_customer(
                    db,
                    tenant_id=tenant.id,
                    channel_type="email",
                    address=normalized.from_email,
                )
                if customer and normalized.from_name and not customer.name:
                    customer.name = normalized.from_name
                messages_processed += 1
                client.store(uid, "+FLAGS", "\\Seen")
                if decision.get("status") == "error":
                    db.flush()
            return EmailPollResult(tenant.id, channel.id, messages_seen, messages_processed)
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

    def poll_tenant_once(self, db: Session, *, tenant_id: int) -> EmailPollResult:
        channel = (
            db.query(ChannelConfig)
            .filter(ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel_type == "email")
            .first()
        )
        if not channel:
            return EmailPollResult(tenant_id, 0, 0, 0, "channel_not_configured")
        return self.poll_channel(db, channel)
