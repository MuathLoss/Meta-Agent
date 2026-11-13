"""Team invitations and the institution's chatbot record (spec v1.2, Phase 1)."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.core.sessions import new_token, utcnow
from app.core.tenancy import (
    ROLE_BUSINESS_ADMIN,
    ROLE_CERTIFICATES,
    ROLE_FINANCE,
    ROLE_OPERATIONS_STAFF,
    ROLE_OWNER,
    ROLE_SUPERVISOR,
    get_current_tenant,
    require_tenant_roles,
)
from app.models.entities import AuditLog, Chatbot, Tenant, TenantInvite
from app.schemas.auth import InviteCreate
from app.services.account_email import invite_email, send_account_email
from app.services.chatbots import ensure_chatbot

router = APIRouter(tags=["team"])
INVITE_TTL = timedelta(days=7)
STAFF_ROLES = {ROLE_OPERATIONS_STAFF, ROLE_SUPERVISOR, ROLE_FINANCE, ROLE_CERTIFICATES}
ANY_MEMBER = (ROLE_OWNER, ROLE_BUSINESS_ADMIN, *sorted(STAFF_ROLES))


def invite_view(invite: TenantInvite) -> dict:
    now = utcnow()
    expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=now.tzinfo)
    status = "accepted" if invite.accepted_at else "revoked" if invite.revoked_at else "expired" if now >= expires else "pending"
    return {"id": invite.id, "email": invite.email, "role_code": invite.role_code, "status": status, "expires_at": expires.isoformat()}


@router.post("/tenants/current/invites")
def create_invite(
    payload: InviteCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    ctx: dict = Depends(require_tenant_roles(ROLE_OWNER, ROLE_BUSINESS_ADMIN)),
):
    role = payload.role_code.strip().upper()
    roles = set(ctx.get("roles", []))
    # Owners invite admins and staff; admins invite staff. Nobody is invited as owner.
    allowed = STAFF_ROLES | ({ROLE_BUSINESS_ADMIN} if roles & {ROLE_OWNER, "PLATFORM_SUPER_ADMIN"} else set())
    if role not in allowed:
        raise HTTPException(status_code=403, detail="You cannot invite someone with this role")
    enforce_rate_limit(f"team:invite:{tenant.id}", max_requests=30, window_seconds=3600)
    email = str(payload.email).lower()
    # A newer invitation replaces any pending one for the same address.
    db.query(TenantInvite).filter(
        TenantInvite.tenant_id == tenant.id, TenantInvite.email == email,
        TenantInvite.accepted_at.is_(None), TenantInvite.revoked_at.is_(None),
    ).update({TenantInvite.revoked_at: utcnow()}, synchronize_session=False)
    raw, token_hash = new_token()
    invite = TenantInvite(
        tenant_id=tenant.id, email=email, role_code=role, token_hash=token_hash,
        invited_by_user_id=getattr(ctx.get("user"), "id", None), expires_at=utcnow() + INVITE_TTL,
    )
    db.add(invite)
    db.flush()
    db.add(AuditLog(tenant_id=tenant.id, actor_user_id=getattr(ctx.get("user"), "id", None), action="team.invite_sent", entity_type="tenant_invite", entity_id=str(invite.id), details_json={"role_code": role}))
    db.commit()
    sent = send_account_email(invite_email(email, tenant.display_name, raw))
    return {**invite_view(invite), "email_sent": sent}


@router.get("/tenants/current/invites")
def list_invites(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_OWNER, ROLE_BUSINESS_ADMIN)),
):
    rows = db.query(TenantInvite).filter(TenantInvite.tenant_id == tenant.id).order_by(TenantInvite.id.desc()).limit(200).all()
    return [invite_view(row) for row in rows]


@router.delete("/tenants/current/invites/{invite_id}")
def revoke_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    ctx: dict = Depends(require_tenant_roles(ROLE_OWNER, ROLE_BUSINESS_ADMIN)),
):
    invite = db.query(TenantInvite).filter(TenantInvite.id == invite_id, TenantInvite.tenant_id == tenant.id).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invite.accepted_at is None and invite.revoked_at is None:
        invite.revoked_at = utcnow()
        db.add(AuditLog(tenant_id=tenant.id, actor_user_id=getattr(ctx.get("user"), "id", None), action="team.invite_revoked", entity_type="tenant_invite", entity_id=str(invite.id), details_json={}))
        db.commit()
    return invite_view(invite)


@router.get("/chatbot")
def get_chatbot(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(*ANY_MEMBER)),
):
    bot: Chatbot = ensure_chatbot(db, tenant)
    db.commit()
    return {
        "id": bot.id,
        "display_name": bot.display_name,
        "status": bot.status,
        "public_widget_id": bot.public_widget_id,
        "language_mode": bot.language_mode,
    }
