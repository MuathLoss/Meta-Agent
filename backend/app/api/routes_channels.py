import re
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import Tenant
from app.schemas.channels import ChannelConfigRequest, ChannelConfigResponse, ChannelTestConsoleRequest, ChannelTestConsoleResponse
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
    message = payload.message.strip()
    preview = test_console_orchestrator.preview_classification(db, tenant=tenant, text=message)
    intent_payload = preview.get("intent") if isinstance(preview, dict) else {}
    route_payload = preview.get("route") if isinstance(preview, dict) else {}
    intent = str(intent_payload.get("intent_code") or "UNKNOWN") if isinstance(intent_payload, dict) else "UNKNOWN"
    confidence = float(intent_payload.get("confidence") or 0) if isinstance(intent_payload, dict) else 0.0
    needs_clarification = bool(intent_payload.get("needs_clarification")) if isinstance(intent_payload, dict) else True
    route_action = str(route_payload.get("action") or "CLARIFY") if isinstance(route_payload, dict) else "CLARIFY"

    if intent in {"HUMAN_REQUEST", "COMPLAINT"} or route_action in {"HANDOFF", "TICKET"}:
        state = "HUMAN_HANDOFF"
        reply = None
        handoff = True
    elif intent == "UNKNOWN" or needs_clarification or confidence < 0.67:
        state = "CLARIFYING"
        reply = test_console_orchestrator.response_engine.clarification_question(tenant)
        handoff = False
    else:
        state = "BOT_ACTIVE"
        reply = test_console_orchestrator.response_engine.build_response(
            db,
            tenant,
            intent,
            faq_topic_key=intent_payload.get("faq_topic_key") if isinstance(intent_payload, dict) else None,
            preferred_lang=(preview.get("language") or {}).get("resolved_lang") if isinstance(preview.get("language"), dict) else None,
        ) or test_console_orchestrator.response_engine.clarification_question(tenant)
        handoff = False

    return ChannelTestConsoleResponse(
        session_id=session_id,
        channel_type=channel_type,
        conversation_id=f"virtual:{tenant.id}:{channel_type}:{session_id}",
        reply=reply,
        state=state,
        handoff=handoff,
        intent=intent,
        notes=["Virtual test only. No inbox conversation, customer, message, or provider send was created."],
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
