from __future__ import annotations

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.entities import ChannelConfig, Tenant, WebhookEvent
from app.services.orchestrator import ConversationOrchestrator
from app.services.telegram_adapter import TelegramAdapter
from app.services.tenant_channel_service import TenantChannelService
from app.services.whatsapp_adapter import WhatsAppAdapter

router = APIRouter(tags=["webhook"])
channel_service = TenantChannelService()
orchestrator = ConversationOrchestrator()
whatsapp_adapter = WhatsAppAdapter()
telegram_adapter = TelegramAdapter()
logger = logging.getLogger(__name__)

ACTIVE_CHANNEL_STATUSES = {"configured", "connected", "active", "not_connected"}


class AmbiguousChannelResolution(Exception):
    pass


def _is_resolvable_channel(row: ChannelConfig) -> bool:
    public_config = row.public_config_json or {}
    if public_config.get("enabled") is False:
        return False
    return row.status in ACTIVE_CHANNEL_STATUSES


def _exactly_one_channel(matches: list[ChannelConfig], *, provider: str, identifier_name: str) -> ChannelConfig | None:
    tenant_ids = sorted({row.tenant_id for row in matches})
    if len(matches) > 1:
        logger.warning(
            "Ambiguous %s webhook channel resolution for %s; matching tenant_ids=%s",
            provider,
            identifier_name,
            tenant_ids,
        )
        raise AmbiguousChannelResolution
    return matches[0] if matches else None


def _stored_event_id(tenant_id: int, provider_event_id: str) -> str:
    # The current DB uniqueness is provider-wide. Prefixing at write time gives
    # tenant-aware idempotency without changing schema in this non-destructive patch.
    return f"tenant:{tenant_id}:{provider_event_id}"


def _resolve_channel_by_secret_token(db: Session, channel_type: str, secret_key: str, secret_value: str | None) -> ChannelConfig | None:
    if not secret_value:
        return None
    matches: list[ChannelConfig] = []
    for row in db.query(ChannelConfig).filter(ChannelConfig.channel_type == channel_type).all():
        if not _is_resolvable_channel(row):
            continue
        creds = channel_service.credentials(row)
        expected_value = creds.get(secret_key)
        if channel_type == "telegram":
            expected_value = telegram_adapter.expected_verification_token(creds)
        if expected_value == secret_value:
            matches.append(row)
    return _exactly_one_channel(matches, provider=channel_type, identifier_name=secret_key)


def _resolve_telegram_channel(db: Session, token_hint: str | None) -> tuple[ChannelConfig | None, str | None]:
    channel = _resolve_channel_by_secret_token(db, "telegram", "secret_token", token_hint)
    if not channel:
        return None, None
    creds = channel_service.credentials(channel)
    return channel, telegram_adapter.expected_verification_token(creds)


def _resolve_channel_by_phone_number_id(db: Session, phone_number_id: str) -> ChannelConfig | None:
    indexed_matches = (
        db.query(ChannelConfig)
        .filter(
            ChannelConfig.channel_type == "whatsapp",
            ChannelConfig.provider_channel_id == phone_number_id,
        )
        .all()
    )
    indexed_matches = [row for row in indexed_matches if _is_resolvable_channel(row)]
    if indexed_matches:
        return _exactly_one_channel(indexed_matches, provider="whatsapp", identifier_name="provider_channel_id")

    fallback_matches: list[ChannelConfig] = []
    for row in db.query(ChannelConfig).filter(ChannelConfig.channel_type == "whatsapp").all():
        if not _is_resolvable_channel(row):
            continue
        public_config = row.public_config_json or {}
        creds = channel_service.credentials(row)
        if public_config.get("phone_number_id") == phone_number_id or creds.get("phone_number_id") == phone_number_id:
            fallback_matches.append(row)
    return _exactly_one_channel(fallback_matches, provider="whatsapp", identifier_name="phone_number_id")


@router.get("/channels/whatsapp/webhook")
def verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    if hub_mode != "subscribe" or not hub_verify_token:
        return {"ok": False}
    try:
        row = _resolve_channel_by_secret_token(db, "whatsapp", "verify_token", hub_verify_token)
    except AmbiguousChannelResolution:
        return {"ok": False, "error": "ambiguous_channel"}
    if row:
        return int(hub_challenge) if hub_challenge and hub_challenge.isdigit() else hub_challenge
    return {"ok": False}


@router.post("/channels/whatsapp/webhook")
async def receive(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {"ok": True, "ignored": "invalid_json"}

    normalized = whatsapp_adapter.normalize_inbound(payload)
    if not normalized:
        return {"ok": True, "ignored": "non_message_or_unrecognized_payload"}

    try:
        channel = _resolve_channel_by_phone_number_id(db, normalized.phone_number_id)
    except AmbiguousChannelResolution:
        return {"ok": True, "ignored": "ambiguous_tenant_channel"}
    if not channel:
        return {"ok": True, "ignored": "unknown_tenant_channel"}

    creds = channel_service.credentials(channel)
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not whatsapp_adapter.valid_signature(raw_body=raw_body, signature_header=signature_header, app_secret=creds.get("app_secret")):
        if settings.allow_unsigned_webhooks_in_dev and settings.app_env == "development":
            pass
        else:
            raise HTTPException(status_code=403, detail="Invalid WhatsApp webhook signature")

    stored_event_id = _stored_event_id(channel.tenant_id, normalized.provider_message_id)
    if db.query(WebhookEvent).filter(WebhookEvent.tenant_id == channel.tenant_id, WebhookEvent.provider == "whatsapp", WebhookEvent.provider_event_id == stored_event_id).first():
        return {"ok": True, "duplicate": True}

    db.add(WebhookEvent(tenant_id=channel.tenant_id, provider="whatsapp", provider_event_id=stored_event_id, event_type="message", payload_json=payload))
    db.flush()
    tenant = db.get(Tenant, channel.tenant_id)
    if not tenant:
        return {"ok": True, "ignored": "tenant_not_found"}
    decision = orchestrator.handle_inbound(
        db,
        tenant=tenant,
        customer_phone=normalized.customer_phone,
        text=normalized.text,
        channel_type="whatsapp",
        provider_message_id=normalized.provider_message_id,
        payload_json=normalized.raw,
    )
    return {"ok": True, "decision": decision}


async def _receive_telegram(request: Request, db: Session, bot_token: str | None = None):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {"ok": True, "ignored": "invalid_json"}

    normalized = telegram_adapter.normalize_inbound(payload)
    if not normalized:
        return {"ok": True, "ignored": "non_message_or_unrecognized_payload"}

    token_hint = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or bot_token
    try:
        channel, expected_token = _resolve_telegram_channel(db, token_hint)
    except AmbiguousChannelResolution:
        return {"ok": True, "ignored": "ambiguous_tenant_channel"}
    if not channel:
        raise HTTPException(status_code=403, detail="Unknown tenant Telegram channel")

    if not telegram_adapter.valid_secret_token(token_hint, expected_token):
        raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

    stored_event_id = _stored_event_id(channel.tenant_id, normalized.provider_message_id)
    if db.query(WebhookEvent).filter(WebhookEvent.tenant_id == channel.tenant_id, WebhookEvent.provider == "telegram", WebhookEvent.provider_event_id == stored_event_id).first():
        return {"ok": True, "duplicate": True}

    db.add(WebhookEvent(tenant_id=channel.tenant_id, provider="telegram", provider_event_id=stored_event_id, event_type="message", payload_json=payload))
    db.flush()
    tenant = db.get(Tenant, channel.tenant_id)
    if not tenant:
        return {"ok": True, "ignored": "tenant_not_found"}
    decision = orchestrator.handle_inbound(
        db,
        tenant=tenant,
        customer_phone=normalized.customer_address,
        text=normalized.text,
        channel_type="telegram",
        provider_message_id=normalized.provider_message_id,
        payload_json=normalized.raw,
    )
    return {"ok": True, "decision": decision}


@router.post("/channels/telegram/webhook")
async def receive_telegram(request: Request, db: Session = Depends(get_db)):
    return await _receive_telegram(request, db)


@router.post("/channels/telegram/webhook/{bot_token:path}")
async def receive_telegram_with_token(bot_token: str, request: Request, db: Session = Depends(get_db)):
    return await _receive_telegram(request, db, bot_token=bot_token)
