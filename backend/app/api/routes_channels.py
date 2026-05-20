import re
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import Conversation, Message, Tenant
from app.schemas.channels import ChannelConfigRequest, ChannelConfigResponse, ChannelTestConsoleRequest, ChannelTestConsoleResponse
from app.services.dry_run_context import dry_run_outbound
from app.services.email_polling_service import EmailPollingService
from app.services.orchestrator import ConversationOrchestrator
from app.services.tenant_channel_service import DuplicateProviderChannelError, TenantChannelService, UnsafePublicConfigError, sanitize_public_config

router = APIRouter(prefix="/channels", tags=["channels"])
service = TenantChannelService()
email_polling_service = EmailPollingService()
test_console_orchestrator = ConversationOrchestrator()
TESTABLE_CHANNELS = {"telegram", "web_chat", "email", "whatsapp", "instagram", "facebook"}
SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")

def ser(r):
    return ChannelConfigResponse(
        channel_type=r.channel_type,
        status=r.status,
        public_config=sanitize_public_config(r.public_config_json),
        provider_channel_id=r.provider_channel_id,
        provider_account_id=r.provider_account_id,
        has_credentials=bool(r.encrypted_credentials),
    )

@router.get("")
def list_channels(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    return [ser(r) for r in service.list(db, tenant.id)]

@router.put("/{channel_type}/settings", response_model=ChannelConfigResponse)
def update(channel_type: str, payload: ChannelConfigRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    try:
        row = service.upsert(db, tenant.id, channel_type, payload.status, payload.public_config, payload.credentials)
    except UnsafePublicConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DuplicateProviderChannelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return ser(row)

def _normalize_test_session_id(session_id: str | None) -> str:
    raw = str(session_id or "").strip()
    if not raw:
        return f"test_{token_urlsafe(12)}"
    normalized = SESSION_ID_RE.sub("-", raw).strip("-._:")
    return (normalized or f"test_{token_urlsafe(12)}")[:80]


def _test_channel_ready(row) -> tuple[bool, str | None]:
    if not row or row.channel_type not in TESTABLE_CHANNELS:
        return False, "channel_not_implemented"
    public_config = row.public_config_json or {}
    if public_config.get("enabled") is not True:
        return False, "channel_disabled"
    if row.status not in {"configured", "connected", "active"}:
        return False, f"channel_status_{row.status}"
    return True, None


@router.post("/test-console/message", response_model=ChannelTestConsoleResponse)
def test_console_message(
    payload: ChannelTestConsoleRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    channel_type = payload.channel_type.strip().lower()
    if channel_type not in TESTABLE_CHANNELS:
        raise HTTPException(status_code=400, detail="Channel is not implemented for test console")
    channel = service.get(db, tenant.id, channel_type)
    ready, reason = _test_channel_ready(channel)
    if not ready:
        raise HTTPException(status_code=403, detail=reason or "channel_not_available")

    session_id = _normalize_test_session_id(payload.session_id)
    test_identity = f"test:{tenant.id}:{channel_type}:{session_id}"
    with dry_run_outbound():
        decision = test_console_orchestrator.handle_inbound(
            db,
            tenant=tenant,
            customer_phone=test_identity,
            text=payload.message.strip(),
            channel_type=channel_type,
            provider_message_id=None,
            payload_json={
                "source": "channel_test_console",
                "session_id": session_id,
                "channel_type": channel_type,
                "dry_run": True,
            },
        )

    customer = test_console_orchestrator.customer_identity.lookup_customer(
        db,
        tenant_id=tenant.id,
        channel_type=channel_type,
        address=test_identity,
    )
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
        row = db.query(Message).filter(Message.tenant_id == tenant.id, Message.id == outbound_message_id, Message.direction == "outbound").first()
        reply = row.text if row else None

    state = conversation.state if conversation else decision.get("state")
    intent_payload = decision.get("intent")
    intent = intent_payload.get("intent_code") if isinstance(intent_payload, dict) else None
    if not intent and conversation:
        intent = conversation.last_intent
    handoff = bool(state == "HUMAN_HANDOFF" or decision.get("status") in {"handoff", "stored"})
    return ChannelTestConsoleResponse(
        session_id=session_id,
        channel_type=channel_type,
        conversation_id=str(conversation.id) if conversation else None,
        reply=reply,
        state=state,
        handoff=handoff,
        intent=intent,
        notes=["Dry-run only. No provider outbound API was called."],
    )

@router.post("/email/{tenant_slug}/poll-once")
def poll_email_once(tenant_slug: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    if tenant.slug != tenant_slug:
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    result = email_polling_service.poll_tenant_once(db, tenant_id=tenant.id)
    db.commit()
    return {
        "tenant_id": tenant.id,
        "channel_id": result.channel_id,
        "messages_seen": result.messages_seen,
        "messages_processed": result.messages_processed,
        "error": result.error,
    }
