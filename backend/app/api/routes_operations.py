from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenancy import (
    ROLE_BUSINESS_ADMIN,
    ROLE_CERTIFICATES,
    ROLE_FINANCE,
    ROLE_OPERATIONS_STAFF,
    ROLE_SUPERVISOR,
    get_current_tenant,
    require_tenant_roles,
)
from app.models.entities import AuditLog, Conversation, Customer, Message, Tenant, Ticket
from app.services.customer_channel_identity_service import CustomerChannelIdentityService
from app.services.orchestrator import ConversationOrchestrator
from app.services.outbound_service import OutboundService

router = APIRouter(tags=["operations"])
ROLES = (ROLE_BUSINESS_ADMIN, ROLE_OPERATIONS_STAFF, ROLE_FINANCE, ROLE_CERTIFICATES, ROLE_SUPERVISOR)
outbound_service = OutboundService()
conversation_orchestrator = ConversationOrchestrator()
customer_identity = CustomerChannelIdentityService()


def audit(db: Session, tenant_id: int, actor_id: int | None, action: str, entity_type: str, entity_id: str | None, details: dict | None = None) -> None:
    db.add(AuditLog(tenant_id=tenant_id, actor_user_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, details_json=details or {}))


class HandoffRequest(BaseModel):
    owner_type: str = "role"
    owner_ref: str = "OPERATIONS_STAFF"
    reason: str | None = None


class ResolveRequest(BaseModel):
    note: str | None = None


class ConversationReplyRequest(BaseModel):
    text: str = Field(min_length=1)


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    preferred_lang: str | None = None
    tags_json: list[str] | None = None
    opt_in: bool | None = None


class TicketCreate(BaseModel):
    conversation_id: int
    ticket_type: str = "handoff"
    priority: str = "normal"
    assigned_to: str | None = None
    details_json: dict = Field(default_factory=dict)


class TicketUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    assigned_to: str | None = None
    details_json: dict | None = None


@router.post("/dashboard/conversations/{conversation_id}/handoff")
def handoff_conversation(conversation_id: int, payload: HandoffRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ROLES))):
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.state = "HUMAN_HANDOFF"
    conv.owner_type = payload.owner_type
    conv.owner_ref = payload.owner_ref
    conv.metadata_json = {}
    audit(db, tenant.id, ctx["user"].id, "conversation.handoff", "conversation", str(conv.id), payload.model_dump())
    db.commit()
    return {"status": "handoff", "conversation_id": conv.id}


@router.post("/dashboard/conversations/{conversation_id}/resolve")
def resolve_conversation(conversation_id: int, payload: ResolveRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ROLES))):
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    metadata = dict(conv.metadata_json or {})
    metadata.pop("has_open_complaint", None)
    conv.state = "BOT_ACTIVE"
    conv.owner_type = "BOT"
    conv.owner_ref = "BOT"
    conv.last_intent = "UNKNOWN"
    conv.metadata_json = metadata
    audit(db, tenant.id, ctx["user"].id, "conversation.resolved", "conversation", str(conv.id), {**payload.model_dump(), "resolved_to_state": "BOT_ACTIVE"})
    db.commit()
    return {"status": "bot_active", "conversation_id": conv.id}


@router.post("/dashboard/conversations/{conversation_id}/reply")
def reply_to_conversation(conversation_id: int, payload: ConversationReplyRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ROLES))):
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.id == conv.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Reply text is required")

    message = outbound_service.send_or_store(
        db,
        tenant_id=tenant.id,
        conversation_id=conv.id,
        channel_type=conv.channel_type,
        destination=customer_identity.delivery_address(customer, conv.channel_type),
        text=text,
        intent_code="MANUAL_REPLY",
    )
    # While the team is talking, the customer's answers go to the team, not the bot.
    taken_over = conversation_orchestrator.hold_for_team(conv)
    conv.updated_at = datetime.now(timezone.utc)
    audit(
        db,
        tenant.id,
        ctx["user"].id,
        "conversation.reply_sent",
        "conversation",
        str(conv.id),
        {
            "channel_type": conv.channel_type,
            "message_id": message.id,
            "send_status": (message.payload_json or {}).get("send_status"),
            "taken_over_from_bot": taken_over,
        },
    )
    db.commit()
    return {
        "status": "sent",
        "conversation_id": conv.id,
        "message_id": message.id,
        "send_status": (message.payload_json or {}).get("send_status"),
    }


@router.post("/dashboard/conversations/{conversation_id}/reopen")
def reopen_conversation(conversation_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ROLES))):
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.state = "BOT_ACTIVE"
    conv.owner_type = "BOT"
    conv.owner_ref = "BOT"
    conv.metadata_json = {}
    audit(db, tenant.id, ctx["user"].id, "conversation.reopened", "conversation", str(conv.id), {})
    db.commit()
    return {"status": "bot_active", "conversation_id": conv.id}


@router.put("/dashboard/customers/{customer_id}")
def update_customer(customer_id: int, payload: CustomerUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ROLES))):
    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(customer, k, v)
    audit(db, tenant.id, ctx["user"].id, "customer.updated", "customer", str(customer.id), payload.model_dump(exclude_none=True))
    db.commit()
    return {"status": "updated"}


@router.post("/tickets")
def create_ticket(payload: TicketCreate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ROLES))):
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.id == payload.conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ticket = Ticket(tenant_id=tenant.id, conversation_id=payload.conversation_id, ticket_type=payload.ticket_type, priority=payload.priority, assigned_to=payload.assigned_to, status="open", details_json=payload.details_json)
    db.add(ticket); db.flush()
    audit(db, tenant.id, ctx["user"].id, "ticket.created", "ticket", str(ticket.id), payload.model_dump())
    db.commit(); db.refresh(ticket)
    return {"id": ticket.id, "status": ticket.status}


@router.put("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, payload: TicketUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ROLES))):
    ticket = db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(ticket, k, v)
    audit(db, tenant.id, ctx["user"].id, "ticket.updated", "ticket", str(ticket.id), payload.model_dump(exclude_none=True))
    db.commit()
    return {"status": "updated"}


@router.get("/audit-logs")
def list_audit_logs(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_SUPERVISOR))):
    rows = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id).order_by(AuditLog.created_at.desc()).limit(200).all()
    return [{"id": r.id, "actor_user_id": r.actor_user_id, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id, "details_json": r.details_json or {}, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
