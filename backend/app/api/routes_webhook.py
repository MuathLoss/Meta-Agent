from __future__ import annotations

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.models.entities import ChannelConfig, Conversation, Message, Tenant, WebhookEvent
from app.services.meta_social_adapter import MetaSocialAdapter
from app.services.orchestrator import ConversationOrchestrator
from app.services.telegram_adapter import TelegramAdapter
from app.services.tenant_channel_service import TenantChannelService
from app.services.web_chat_adapter import WebChatAdapter
from app.services.whatsapp_adapter import WhatsAppAdapter

router = APIRouter(tags=["webhook"])
channel_service = TenantChannelService()
orchestrator = ConversationOrchestrator()
whatsapp_adapter = WhatsAppAdapter()
telegram_adapter = TelegramAdapter()
web_chat_adapter = WebChatAdapter()
meta_social_adapter = MetaSocialAdapter()
logger = logging.getLogger(__name__)

ACTIVE_CHANNEL_STATUSES = {"configured", "connected", "active", "not_connected"}
WEBHOOK_DEV_ENVS = {"development", "dev", "test", "testing", "local"}
WEBHOOK_RATE_LIMIT_MAX = 120
WEBHOOK_RATE_LIMIT_WINDOW_SECONDS = 60


class AmbiguousChannelResolution(Exception):
    pass


class WebChatMessageRequest(BaseModel):
    visitor_id: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    display_name: str | None = Field(default=None, max_length=120)


class EmailInboundTestRequest(BaseModel):
    from_email: EmailStr
    from_name: str | None = Field(default=None, max_length=120)
    subject: str | None = Field(default=None, max_length=255)
    text: str = Field(min_length=1, max_length=12000)


class MetaSocialInboundTestRequest(BaseModel):
    sender_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    display_name: str | None = Field(default=None, max_length=120)


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


def _web_chat_enabled(channel: ChannelConfig | None) -> bool:
    if not channel:
        return False
    public_config = channel.public_config_json or {}
    if public_config.get("enabled") is False:
        return False
    return channel.status in {"configured", "connected", "active"}


def _email_enabled(channel: ChannelConfig | None) -> bool:
    if not channel:
        return False
    public_config = channel.public_config_json or {}
    if public_config.get("enabled") is False:
        return False
    return channel.status in {"configured", "connected", "active"}


def _meta_social_enabled(channel: ChannelConfig | None) -> bool:
    if not channel:
        return False
    public_config = channel.public_config_json or {}
    if public_config.get("enabled") is False:
        return False
    return channel.status in {"configured", "connected", "active"}


def _configured_secret(value: object) -> bool:
    return settings.configured(value)


def _latest_outbound_text(db: Session, *, tenant_id: int, outbound_message_id: int | None) -> str | None:
    if outbound_message_id is None:
        return None
    row = (
        db.query(Message)
        .filter(Message.tenant_id == tenant_id, Message.id == outbound_message_id, Message.direction == "outbound")
        .first()
    )
    return row.text if row else None


def _allow_unsigned_whatsapp_webhook(signature_header: str | None) -> bool:
    if signature_header:
        return False
    return settings.allow_unsigned_webhooks_in_dev and settings.app_env.lower() in WEBHOOK_DEV_ENVS


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
    enforce_rate_limit(
        f"webhook:whatsapp:{client_ip(request)}",
        max_requests=WEBHOOK_RATE_LIMIT_MAX,
        window_seconds=WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
    )
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
    app_secret = creds.get("app_secret")
    if not whatsapp_adapter.usable_app_secret(app_secret):
        if not _allow_unsigned_whatsapp_webhook(signature_header):
            raise HTTPException(status_code=403, detail="WhatsApp webhook app secret is not configured")
    elif not whatsapp_adapter.valid_signature(raw_body=raw_body, signature_header=signature_header, app_secret=app_secret):
        if not _allow_unsigned_whatsapp_webhook(signature_header):
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
    enforce_rate_limit(
        f"webhook:telegram:{client_ip(request)}",
        max_requests=WEBHOOK_RATE_LIMIT_MAX,
        window_seconds=WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
    )
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
    if settings.app_env.lower() not in WEBHOOK_DEV_ENVS:
        raise HTTPException(status_code=404, detail="Telegram token-in-path webhook is disabled")
    return await _receive_telegram(request, db, bot_token=bot_token)


@router.post("/channels/web-chat/{tenant_slug}/message")
def receive_web_chat_message(
    tenant_slug: str,
    payload: WebChatMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    enforce_rate_limit(
        f"webhook:web_chat:{tenant_slug}:{client_ip(request)}",
        max_requests=WEBHOOK_RATE_LIMIT_MAX,
        window_seconds=WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
    )
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug, Tenant.status == "active").first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    channel = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "web_chat")
        .first()
    )
    if not _web_chat_enabled(channel):
        raise HTTPException(status_code=403, detail="Web chat is not enabled for this tenant")

    normalized = web_chat_adapter.normalize_inbound(payload.model_dump())
    if not normalized:
        raise HTTPException(status_code=400, detail="Message text is required")

    visitor_address = f"{tenant.id}:{normalized.visitor_id}"
    decision = orchestrator.handle_inbound(
        db,
        tenant=tenant,
        customer_phone=visitor_address,
        text=normalized.text,
        channel_type="web_chat",
        provider_message_id=None,
        payload_json={
            **normalized.raw,
            "tenant_slug": tenant.slug,
        },
    )

    customer_identity = orchestrator.customer_identity
    customer = customer_identity.lookup_customer(
        db,
        tenant_id=tenant.id,
        channel_type="web_chat",
        address=visitor_address,
    )
    if customer and normalized.display_name and not customer.name:
        customer.name = normalized.display_name
        db.commit()

    conversation = None
    if customer:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant.id,
                Conversation.customer_id == customer.id,
                Conversation.channel_type == "web_chat",
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .first()
        )

    outbound_message_id = decision.get("outbound_message_id")
    reply = decision.get("auto_reply")
    if not reply and isinstance(outbound_message_id, int):
        reply = _latest_outbound_text(db, tenant_id=tenant.id, outbound_message_id=outbound_message_id)

    state = conversation.state if conversation else decision.get("state")
    handoff = bool(state == "HUMAN_HANDOFF" or decision.get("status") in {"handoff", "stored"})
    return {
        "visitor_id": normalized.visitor_id,
        "conversation_id": str(conversation.id) if conversation else None,
        "reply": reply,
        "state": state,
        "handoff": handoff,
    }


@router.post("/channels/email/{tenant_slug}/inbound-test")
def receive_email_inbound_test(
    tenant_slug: str,
    payload: EmailInboundTestRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    enforce_rate_limit(
        f"webhook:email:{tenant_slug}:{client_ip(request)}",
        max_requests=WEBHOOK_RATE_LIMIT_MAX,
        window_seconds=WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
    )
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug, Tenant.status == "active").first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    channel = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "email")
        .first()
    )
    if not _email_enabled(channel):
        raise HTTPException(status_code=403, detail="Email channel is not enabled for this tenant")

    creds = channel_service.credentials(channel)
    configured_secret = creds.get("inbound_webhook_secret")
    provided_secret = request.headers.get("X-Channel-Webhook-Secret")
    if _configured_secret(configured_secret):
        if provided_secret != configured_secret:
            raise HTTPException(status_code=403, detail="Invalid email inbound secret")
    elif not (settings.allow_unsigned_webhooks_in_dev and settings.app_env.lower() in WEBHOOK_DEV_ENVS):
        raise HTTPException(status_code=403, detail="Email inbound secret is required")

    from_email = str(payload.from_email).strip().lower()
    decision = orchestrator.handle_inbound(
        db,
        tenant=tenant,
        customer_phone=from_email,
        text=payload.text.strip(),
        channel_type="email",
        provider_message_id=None,
        payload_json={
            "source": "email_inbound_test",
            "from_email": from_email,
            "from_name_provided": bool(payload.from_name and payload.from_name.strip()),
            "subject_provided": bool(payload.subject and payload.subject.strip()),
        },
    )

    customer_identity = orchestrator.customer_identity
    customer = customer_identity.lookup_customer(
        db,
        tenant_id=tenant.id,
        channel_type="email",
        address=from_email,
    )
    if customer and payload.from_name and payload.from_name.strip() and not customer.name:
        customer.name = payload.from_name.strip()
        db.commit()

    conversation = None
    if customer:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant.id,
                Conversation.customer_id == customer.id,
                Conversation.channel_type == "email",
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .first()
        )

    outbound_message_id = decision.get("outbound_message_id")
    reply = decision.get("auto_reply")
    if not reply and isinstance(outbound_message_id, int):
        reply = _latest_outbound_text(db, tenant_id=tenant.id, outbound_message_id=outbound_message_id)

    state = conversation.state if conversation else decision.get("state")
    handoff = bool(state == "HUMAN_HANDOFF" or decision.get("status") in {"handoff", "stored"})
    return {
        "conversation_id": str(conversation.id) if conversation else None,
        "state": state,
        "handoff": handoff,
        "reply": reply,
    }


def _receive_meta_social_inbound_test(
    channel_type: str,
    tenant_slug: str,
    payload: MetaSocialInboundTestRequest,
    request: Request,
    db: Session,
):
    enforce_rate_limit(
        f"webhook:{channel_type}:{tenant_slug}:{client_ip(request)}",
        max_requests=WEBHOOK_RATE_LIMIT_MAX,
        window_seconds=WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
    )
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug, Tenant.status == "active").first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    channel = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == channel_type)
        .first()
    )
    if not _meta_social_enabled(channel):
        label = "Instagram" if channel_type == "instagram" else "Facebook Messenger"
        raise HTTPException(status_code=403, detail=f"{label} channel is not enabled for this tenant")

    creds = channel_service.credentials(channel)
    configured_secret = creds.get("webhook_secret")
    provided_secret = request.headers.get("X-Channel-Webhook-Secret")
    if _configured_secret(configured_secret):
        if provided_secret != configured_secret:
            raise HTTPException(status_code=403, detail="Invalid social inbound secret")
    elif not (settings.allow_unsigned_webhooks_in_dev and settings.app_env.lower() in WEBHOOK_DEV_ENVS):
        raise HTTPException(status_code=403, detail="Social inbound secret is required")

    normalized = meta_social_adapter.normalize_inbound_test(channel_type=channel_type, payload=payload.model_dump())
    if not normalized:
        raise HTTPException(status_code=400, detail="Sender id and message text are required")

    synthetic_address = f"{tenant.id}:{normalized.sender_id}"
    decision = orchestrator.handle_inbound(
        db,
        tenant=tenant,
        customer_phone=synthetic_address,
        text=normalized.text,
        channel_type=channel_type,
        provider_message_id=None,
        payload_json={
            **normalized.raw,
            "tenant_slug": tenant.slug,
        },
    )

    customer_identity = orchestrator.customer_identity
    customer = customer_identity.lookup_customer(
        db,
        tenant_id=tenant.id,
        channel_type=channel_type,
        address=synthetic_address,
    )
    if customer and normalized.display_name and not customer.name:
        customer.name = normalized.display_name
        db.commit()

    conversation = None
    if customer:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant.id,
                Conversation.customer_id == customer.id,
                Conversation.channel_type == channel_type,
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .first()
        )

    outbound_message_id = decision.get("outbound_message_id")
    reply = decision.get("auto_reply")
    if not reply and isinstance(outbound_message_id, int):
        reply = _latest_outbound_text(db, tenant_id=tenant.id, outbound_message_id=outbound_message_id)

    state = conversation.state if conversation else decision.get("state")
    handoff = bool(state == "HUMAN_HANDOFF" or decision.get("status") in {"handoff", "stored"})
    return {
        "conversation_id": str(conversation.id) if conversation else None,
        "state": state,
        "handoff": handoff,
        "reply": reply,
    }


@router.post("/channels/instagram/{tenant_slug}/inbound-test")
def receive_instagram_inbound_test(
    tenant_slug: str,
    payload: MetaSocialInboundTestRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    return _receive_meta_social_inbound_test("instagram", tenant_slug, payload, request, db)


@router.post("/channels/facebook/{tenant_slug}/inbound-test")
def receive_facebook_inbound_test(
    tenant_slug: str,
    payload: MetaSocialInboundTestRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    return _receive_meta_social_inbound_test("facebook", tenant_slug, payload, request, db)
