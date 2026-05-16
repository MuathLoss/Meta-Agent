from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenancy import ROLE_BROADCAST_OPERATOR, ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import AuditLog, Broadcast, BroadcastRecipient, Tenant
from app.services.broadcast_service import BroadcastService

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])
service = BroadcastService()


class BroadcastCreateRequest(BaseModel):
    title: str
    channel_type: str = "whatsapp"
    template_ref: str | None = None
    audience_type: str = "selected"
    schedule_at: datetime | None = None
    payload: dict = Field(default_factory=dict)


class BroadcastUpdateRequest(BaseModel):
    title: str | None = None
    channel_type: str | None = None
    template_ref: str | None = None
    audience_type: str | None = None
    schedule_at: datetime | None = None
    payload: dict | None = None


class BroadcastScheduleRequest(BaseModel):
    schedule_at: datetime


def _get_broadcast(db: Session, tenant_id: int, broadcast_id: int) -> Broadcast:
    row = db.query(Broadcast).filter(Broadcast.tenant_id == tenant_id, Broadcast.id == broadcast_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    return row


@router.get("")
def list_broadcasts(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    rows = db.query(Broadcast).filter(Broadcast.tenant_id == tenant.id).order_by(Broadcast.created_at.desc()).limit(100).all()
    return [{
        "id": b.id,
        "title": b.title,
        "status": b.status,
        "channel_type": b.channel_type,
        "template_ref": b.template_ref,
        "audience_type": b.audience_type,
        "schedule_at": b.schedule_at.isoformat() if b.schedule_at else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "message_text": (b.payload_json or {}).get("message_text"),
    } for b in rows]


@router.post("")
def create_broadcast(payload: BroadcastCreateRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    status = "scheduled" if payload.schedule_at else "draft"
    row = Broadcast(
        tenant_id=tenant.id,
        title=payload.title,
        channel_type=payload.channel_type,
        template_ref=payload.template_ref,
        audience_type=payload.audience_type,
        schedule_at=payload.schedule_at,
        status=status,
        created_by=ctx["user"].id,
        payload_json=payload.payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.put("/{broadcast_id}")
def update_broadcast(broadcast_id: int, payload: BroadcastUpdateRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    row = _get_broadcast(db, tenant.id, broadcast_id)
    if row.status in {"sending", "sent"}:
        raise HTTPException(status_code=400, detail="Sent broadcasts cannot be edited")
    updated_fields = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    if "title" in updated_fields and payload.title is not None:
        row.title = payload.title
    if "channel_type" in updated_fields and payload.channel_type is not None:
        row.channel_type = payload.channel_type
    if "template_ref" in updated_fields:
        row.template_ref = payload.template_ref
    if "audience_type" in updated_fields and payload.audience_type is not None:
        row.audience_type = payload.audience_type
    if "schedule_at" in updated_fields:
        row.schedule_at = payload.schedule_at
        if payload.schedule_at is not None:
            row.status = "scheduled"
    if "payload" in updated_fields and payload.payload is not None:
        row.payload_json = {**(row.payload_json or {}), **payload.payload}
    db.add(AuditLog(
        tenant_id=tenant.id,
        actor_user_id=ctx["user"].id,
        action="broadcast.updated",
        entity_type="broadcast",
        entity_id=str(row.id),
        details_json={"status": row.status, "channel_type": row.channel_type, "title": row.title},
    ))
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.post("/{broadcast_id}/schedule")
def schedule_broadcast(broadcast_id: int, payload: BroadcastScheduleRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    row = _get_broadcast(db, tenant.id, broadcast_id)
    result = service.schedule(db, tenant=tenant, broadcast=row, schedule_at=payload.schedule_at, actor_user_id=ctx["user"].id)
    db.commit()
    return result.__dict__


@router.post("/{broadcast_id}/send")
def send_broadcast(broadcast_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    row = _get_broadcast(db, tenant.id, broadcast_id)
    try:
        result = service.send_now(db, tenant=tenant, broadcast=row, actor_user_id=ctx["user"].id)
        db.commit()
        return result.__dict__
    except ValueError as exc:
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{broadcast_id}/cancel")
def cancel_broadcast(broadcast_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    row = _get_broadcast(db, tenant.id, broadcast_id)
    result = service.cancel(db, tenant=tenant, broadcast=row, actor_user_id=ctx["user"].id)
    db.commit()
    return result.__dict__


@router.delete("/{broadcast_id}")
def delete_broadcast(broadcast_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    row = _get_broadcast(db, tenant.id, broadcast_id)
    db.add(AuditLog(
        tenant_id=tenant.id,
        actor_user_id=ctx["user"].id,
        action="broadcast.deleted",
        entity_type="broadcast",
        entity_id=str(row.id),
        details_json={"status": row.status, "channel_type": row.channel_type, "title": row.title},
    ))
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": broadcast_id}


@router.get("/{broadcast_id}/recipients")
def broadcast_recipients(broadcast_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN, ROLE_BROADCAST_OPERATOR))):
    _get_broadcast(db, tenant.id, broadcast_id)
    rows = db.query(BroadcastRecipient).filter(BroadcastRecipient.tenant_id == tenant.id, BroadcastRecipient.broadcast_id == broadcast_id).order_by(BroadcastRecipient.id.asc()).all()
    return [{
        "id": r.id,
        "customer_id": r.customer_id,
        "status": r.status,
        "provider_message_id": r.provider_message_id,
        "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
    } for r in rows]
