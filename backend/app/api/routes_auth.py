from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.rate_limit import client_ip, enforce_rate_limit, normalized_identifier
from app.core.security import create_access_token, hash_password, verify_password
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, get_current_user, require_tenant_roles
from app.models.entities import (
    AuditLog,
    ImportJob,
    Branch,
    Broadcast,
    BroadcastRecipient,
    BusinessSetting,
    ChannelConfig,
    Conversation,
    Customer,
    FaqItem,
    Message,
    RoutingRule,
    Tenant,
    TenantBrand,
    TenantUserRole,
    Ticket,
    TrainingExample,
    User,
    WebhookEvent,
    IntentDefinition,
    IntentKeyword,
)
from app.schemas.auth import DeleteAccountRequest, LoginRequest, SignupBusinessRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])
LOGIN_RATE_LIMIT_MAX = 10
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300
SIGNUP_RATE_LIMIT_MAX = 5
SIGNUP_RATE_LIMIT_WINDOW_SECONDS = 3600


def delete_local_logo_file(logo_url: str | None) -> None:
    if not logo_url or not logo_url.startswith("/uploads/tenant_logos/"):
        return
    relative_path = logo_url.removeprefix("/uploads/")
    file_path = Path(__file__).resolve().parents[2] / "uploads" / relative_path
    if file_path.exists() and file_path.is_file():
        file_path.unlink()

def memberships(db: Session, user: User) -> list[dict]:
    rows = db.query(TenantUserRole, Tenant).join(Tenant, Tenant.id == TenantUserRole.tenant_id).filter(TenantUserRole.user_id == user.id, TenantUserRole.is_active.is_(True)).all()
    data: dict[int, dict] = {}
    for role, tenant in rows:
        data.setdefault(tenant.id, {"tenant_id": tenant.id, "tenant_slug": tenant.slug, "tenant_name": tenant.display_name, "roles": []})["roles"].append(role.role_code)
    return list(data.values())

def resolve_login_tenant_slug(requested_slug: str | None, memberships_list: list[dict]) -> str | None:
    if not memberships_list:
        return None
    if not requested_slug:
        return memberships_list[0]["tenant_slug"]
    match = next((item for item in memberships_list if item["tenant_slug"] == requested_slug), None)
    if not match:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return match["tenant_slug"]

@router.post("/signup-business", response_model=TokenResponse)
def signup(payload: SignupBusinessRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(
        f"auth:signup:{client_ip(request)}",
        max_requests=SIGNUP_RATE_LIMIT_MAX,
        window_seconds=SIGNUP_RATE_LIMIT_WINDOW_SECONDS,
    )
    if db.query(Tenant).filter(Tenant.slug == payload.tenant_slug).first():
        raise HTTPException(status_code=409, detail="Tenant slug is already used")
    if db.query(User).filter(User.email == str(payload.admin_email).lower()).first():
        raise HTTPException(status_code=409, detail="Admin email is already used")
    tenant = Tenant(slug=payload.tenant_slug, display_name=payload.business_name, legal_name=payload.business_name, timezone=payload.timezone, default_lang=payload.default_lang, status="draft")
    db.add(tenant); db.flush()
    user = User(email=str(payload.admin_email).lower(), full_name=payload.admin_name, password_hash=hash_password(payload.admin_password))
    db.add(user); db.flush()
    db.add(TenantBrand(tenant_id=tenant.id, primary_color="#5b0f20", support_email=str(payload.support_email) if payload.support_email else None, support_phone=payload.support_phone))
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    for channel, status in [("whatsapp", "not_connected"), ("telegram", "not_connected"), ("email", "future"), ("instagram", "future"), ("facebook", "future"), ("web_chat", "future")]:
        db.add(ChannelConfig(tenant_id=tenant.id, channel_type=channel, status=status, public_config_json={"enabled": channel == "whatsapp"}))
    db.commit()
    claims = {"tenant_slug": tenant.slug, "is_platform_admin": False}
    return TokenResponse(access_token=create_access_token(str(user.id), claims), user={"id": user.id, "email": user.email, "full_name": user.full_name, "is_platform_admin": user.is_platform_admin}, memberships=memberships(db, user))

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(
        f"auth:login:{client_ip(request)}:{normalized_identifier(payload.email)}",
        max_requests=LOGIN_RATE_LIMIT_MAX,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    user = db.query(User).filter(User.email == str(payload.email).lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    m = memberships(db, user)
    slug = resolve_login_tenant_slug(payload.tenant_slug, m)
    claims = {"tenant_slug": slug, "is_platform_admin": user.is_platform_admin}
    return TokenResponse(access_token=create_access_token(str(user.id), claims), user={"id": user.id, "email": user.email, "full_name": user.full_name, "is_platform_admin": user.is_platform_admin}, memberships=m)

@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "is_platform_admin": user.is_platform_admin, "memberships": memberships(db, user)}


@router.delete("/account")
def delete_account(
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    if user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admins cannot use self-serve account deletion")

    roles = ctx.get("roles", [])
    if ROLE_BUSINESS_ADMIN not in roles:
        raise HTTPException(status_code=403, detail="Only a business admin can delete this account")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    brand = db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant.id).first()
    if brand:
        delete_local_logo_file(brand.logo_url)

    remaining_memberships = (
        db.query(TenantUserRole)
        .filter(
            TenantUserRole.user_id == user.id,
            TenantUserRole.tenant_id != tenant.id,
            TenantUserRole.is_active.is_(True),
        )
        .count()
    )

    deleted_tenant = {"id": tenant.id, "slug": tenant.slug}
    db.query(ImportJob).filter(ImportJob.tenant_id == tenant.id).delete()
    db.query(BroadcastRecipient).filter(BroadcastRecipient.tenant_id == tenant.id).delete()
    db.query(Broadcast).filter(Broadcast.tenant_id == tenant.id).delete()
    db.query(Ticket).filter(Ticket.tenant_id == tenant.id).delete()
    db.query(Message).filter(Message.tenant_id == tenant.id).delete()
    db.query(Conversation).filter(Conversation.tenant_id == tenant.id).delete()
    db.query(Customer).filter(Customer.tenant_id == tenant.id).delete()
    db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id).delete()
    db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id).delete()
    db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id).delete()
    db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id).delete()
    db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id).delete()
    db.query(BusinessSetting).filter(BusinessSetting.tenant_id == tenant.id).delete()
    db.query(Branch).filter(Branch.tenant_id == tenant.id).delete()
    db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id).delete()
    db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant.id).delete()
    db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id).delete()
    db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id).delete()
    db.query(WebhookEvent).filter(WebhookEvent.tenant_id == tenant.id).delete()
    db.delete(tenant)
    if remaining_memberships == 0:
        db.delete(user)
    db.commit()

    return {
        "status": "deleted",
        "deleted_tenant": deleted_tenant,
        "deleted_user": remaining_memberships == 0,
    }
