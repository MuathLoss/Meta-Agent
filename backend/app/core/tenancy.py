from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import get_token_payload
from app.models.entities import AuditLog, Tenant, TenantUserRole, User

ROLE_BUSINESS_ADMIN = "BUSINESS_ADMIN"
ROLE_OPERATIONS_STAFF = "OPERATIONS_STAFF"
ROLE_FINANCE = "FINANCE"
ROLE_CERTIFICATES = "CERTIFICATES"
ROLE_SUPERVISOR = "SUPERVISOR"
ROLE_BROADCAST_OPERATOR = "BROADCAST_OPERATOR"

def get_current_user(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)) -> User:
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")
    return user

def get_current_tenant(
    x_tenant_slug: str | None = Header(default=None, alias="X-Tenant-Slug"),
    x_support_access_reason: str | None = Header(default=None, alias="X-Support-Access-Reason"),
    payload: dict = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> Tenant:
    slug = x_tenant_slug or payload.get("tenant_slug")
    if not slug:
        raise HTTPException(status_code=400, detail="X-Tenant-Slug header is required")
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    user = db.get(User, int(payload["sub"]))
    if user and user.is_platform_admin:
        reason = (x_support_access_reason or "").strip()
        if not reason:
            raise HTTPException(status_code=403, detail="Support access reason is required")
        db.add(AuditLog(
            tenant_id=tenant.id,
            actor_user_id=user.id,
            action="support.tenant_access",
            entity_type="tenant",
            entity_id=str(tenant.id),
            details_json={"tenant_slug": tenant.slug, "reason": reason},
        ))
        db.commit()
    return tenant

def user_roles_for_tenant(db: Session, user_id: int, tenant_id: int) -> list[str]:
    rows = db.query(TenantUserRole).filter(TenantUserRole.user_id == user_id, TenantUserRole.tenant_id == tenant_id, TenantUserRole.is_active.is_(True)).all()
    return [r.role_code for r in rows]

def require_tenant_roles(*allowed_roles: str):
    def dep(db: Session = Depends(get_db), user: User = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)) -> dict:
        if user.is_platform_admin:
            return {"user": user, "tenant": tenant, "roles": ["PLATFORM_SUPER_ADMIN"]}
        roles = user_roles_for_tenant(db, user.id, tenant.id)
        if not set(roles).intersection(allowed_roles):
            raise HTTPException(status_code=403, detail="Not allowed for this tenant")
        return {"user": user, "tenant": tenant, "roles": roles}
    return dep
