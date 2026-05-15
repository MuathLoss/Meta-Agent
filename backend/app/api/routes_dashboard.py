from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_
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
from app.models.entities import Conversation, Customer, Message, Tenant, Ticket
from app.services.customer_channel_identity_service import CustomerChannelIdentityService
from app.services.orchestrator import ConversationOrchestrator

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
orchestrator = ConversationOrchestrator()
customer_identity = CustomerChannelIdentityService()
ROLES = (ROLE_BUSINESS_ADMIN, ROLE_OPERATIONS_STAFF, ROLE_FINANCE, ROLE_CERTIFICATES, ROLE_SUPERVISOR)


class PreviewInboundRequest(BaseModel):
    customer_phone: str
    text: str
    channel_type: str = "whatsapp"


def last_message_for(db: Session, tenant_id: int, conversation_id: int) -> Message | None:
    return db.query(Message).filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).first()


@router.get("/inbox")
def inbox(
    state: str | None = Query(default=None),
    owner_ref: str | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(*ROLES)),
):
    q = (
        db.query(Conversation, Customer)
        .join(
            Customer,
            and_(
                Customer.id == Conversation.customer_id,
                Customer.tenant_id == Conversation.tenant_id,
            ),
        )
        .filter(Conversation.tenant_id == tenant.id, Customer.tenant_id == tenant.id)
    )
    if state:
        q = q.filter(Conversation.state == state)
    if owner_ref:
        q = q.filter(Conversation.owner_ref == owner_ref)
    rows = q.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).all()
    data = []
    seen_keys: set[tuple[int, str]] = set()
    for conv, customer in rows:
        key = (customer.id, conv.channel_type)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        msg = last_message_for(db, tenant.id, conv.id)
        data.append({
            "id": conv.id,
            "customer_id": customer.id,
            "customer_phone": customer_identity.display_identity(customer),
            "customer_name": customer.name,
            "state": conv.state,
            "channel_type": conv.channel_type,
            "owner_type": conv.owner_type,
            "owner_ref": conv.owner_ref,
            "last_intent": conv.last_intent,
            "metadata_json": conv.metadata_json or {},
            "last_message": msg.text if msg else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        })
        if len(data) >= 100:
            break
    return data


@router.get("/conversations/{conversation_id}")
def detail(conversation_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(*ROLES))):
    row = (
        db.query(Conversation, Customer)
        .join(
            Customer,
            and_(
                Customer.id == Conversation.customer_id,
                Customer.tenant_id == Conversation.tenant_id,
            ),
        )
        .filter(
            Conversation.tenant_id == tenant.id,
            Customer.tenant_id == tenant.id,
            Conversation.id == conversation_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    c, customer = row
    msgs = db.query(Message).filter(Message.tenant_id == tenant.id, Message.conversation_id == c.id).order_by(Message.created_at).all()
    return {
        "conversation": {"id": c.id, "state": c.state, "channel_type": c.channel_type, "owner_type": c.owner_type, "owner_ref": c.owner_ref, "last_intent": c.last_intent, "metadata_json": c.metadata_json or {}},
        "customer": {"id": customer.id, "phone": customer_identity.display_identity(customer), "name": customer.name, "email": customer.email, "tags_json": customer.tags_json or [], "opt_in": customer.opt_in},
        "messages": [{"id": m.id, "direction": m.direction, "text": m.text, "intent_code": m.intent_code, "created_at": m.created_at.isoformat() if m.created_at else None} for m in msgs],
    }


@router.get("/customers")
def customers(search: str | None = Query(default=None), db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(*ROLES))):
    q = db.query(Customer).filter(Customer.tenant_id == tenant.id)
    if search:
        pattern = f"%{search}%"
        q = q.filter((Customer.phone.ilike(pattern)) | (Customer.name.ilike(pattern)))
    rows = q.order_by(Customer.created_at.desc()).limit(100).all()
    return [{"id": r.id, "phone": customer_identity.display_identity(r), "name": r.name, "email": r.email, "preferred_lang": r.preferred_lang, "tags_json": r.tags_json or [], "opt_in": r.opt_in} for r in rows]


@router.get("/tickets")
def tickets(status: str | None = Query(default=None), db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(*ROLES))):
    q = db.query(Ticket).filter(Ticket.tenant_id == tenant.id)
    if status:
        q = q.filter(Ticket.status == status)
    rows = q.order_by(Ticket.created_at.desc()).limit(100).all()
    return [{"id": r.id, "conversation_id": r.conversation_id, "ticket_type": r.ticket_type, "priority": r.priority, "assigned_to": r.assigned_to, "status": r.status, "details_json": r.details_json or {}} for r in rows]


@router.get("/analytics/summary")
def summary(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(*ROLES))):
    by_state = {}
    for state in ["BOT_ACTIVE", "CLARIFYING", "WAITING_FOR_HANDOFF_CONFIRMATION", "HUMAN_HANDOFF", "CLOSED"]:
        by_state[state] = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.state == state).count()
    return {
        "customers": db.query(Customer).filter(Customer.tenant_id == tenant.id).count(),
        "conversations": db.query(Conversation).filter(Conversation.tenant_id == tenant.id).count(),
        "messages": db.query(Message).filter(Message.tenant_id == tenant.id).count(),
        "open_tickets": db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.status == "open").count(),
        "conversation_states": by_state,
    }


@router.post("/preview/inbound")
def preview(payload: PreviewInboundRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(*ROLES))):
    return {"decision": orchestrator.handle_inbound(db, tenant=tenant, customer_phone=payload.customer_phone, text=payload.text, channel_type=payload.channel_type, provider_message_id=None, payload_json={"source": "dashboard_preview"})}
