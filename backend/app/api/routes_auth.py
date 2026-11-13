from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.core.db import get_db, system_scope
from app.core.passwords import hash_password, verify_and_upgrade, verify_password
from app.core.rate_limit import client_ip, enforce_rate_limit, normalized_identifier
from app.core.security import get_token_payload
from app.core.sessions import (
    aware,
    clear_session_cookie,
    create_session,
    csrf_token_for,
    hash_token,
    new_token,
    revoke_all_sessions,
    revoke_session,
    set_session_cookie,
    utcnow,
)
from app.core.tenancy import ROLE_BUSINESS_ADMIN, ROLE_OWNER, get_current_tenant, get_current_user, require_tenant_roles
from app.models.entities import (
    AuditLog,
    Chatbot,
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
    TenantInvite,
    TenantUserRole,
    Ticket,
    TrainingExample,
    User,
    UserToken,
    WebhookEvent,
    IntentDefinition,
    IntentKeyword,
)
from app.schemas.auth import (
    DeleteAccountRequest,
    InviteAccept,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionResponse,
    SignupBusinessRequest,
    TokenRequest,
)
from app.services.account_email import password_reset_email, send_account_email, verification_email
from app.services.chatbots import ensure_chatbot

router = APIRouter(prefix="/auth", tags=["auth"])
LOGIN_RATE_LIMIT_MAX = 10
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300
SIGNUP_RATE_LIMIT_MAX = 5
SIGNUP_RATE_LIMIT_WINDOW_SECONDS = 3600
EMAIL_LINK_RATE_LIMIT_MAX = 5
EMAIL_LINK_RATE_LIMIT_WINDOW_SECONDS = 3600
VERIFY_EMAIL_TTL = timedelta(hours=48)
PASSWORD_RESET_TTL = timedelta(hours=1)
PURPOSE_VERIFY_EMAIL = "verify_email"
PURPOSE_PASSWORD_RESET = "password_reset"


def user_summary(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_platform_admin": user.is_platform_admin,
        "email_verified": user.email_verified_at is not None,
    }


def start_session(db: Session, request: Request, response: Response, user: User, tenant_slug: str | None) -> SessionResponse:
    """Sign the browser in: a new session every time, so an old cookie never carries over."""
    raw, row = create_session(db, user_id=user.id, tenant_slug=tenant_slug, user_agent=request.headers.get("user-agent") if hasattr(request, "headers") else None)
    db.commit()
    set_session_cookie(response, raw)
    return SessionResponse(user=user_summary(user), memberships=memberships(db, user), tenant_slug=tenant_slug, csrf_token=csrf_token_for(row.token_hash))


def issue_user_token(db: Session, user: User, purpose: str, ttl: timedelta) -> str:
    # One live link per purpose: asking again replaces the older link.
    db.query(UserToken).filter(UserToken.user_id == user.id, UserToken.purpose == purpose, UserToken.used_at.is_(None)).update(
        {UserToken.used_at: utcnow()}, synchronize_session=False
    )
    raw, token_hash = new_token()
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=token_hash, expires_at=utcnow() + ttl))
    return raw


def consume_user_token(db: Session, raw: str, purpose: str) -> UserToken:
    row = db.query(UserToken).filter(UserToken.token_hash == hash_token(raw), UserToken.purpose == purpose).first()
    if row is None or row.used_at is not None or utcnow() >= aware(row.expires_at):
        raise HTTPException(status_code=400, detail="This link is invalid or has expired. Ask for a new one.")
    row.used_at = utcnow()
    return row


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

@router.post("/signup-business", response_model=SessionResponse)
def signup(payload: SignupBusinessRequest, request: Request, response: Response, db: Session = Depends(get_db)):
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
    # The person who signs up owns the workspace (spec v1.2 roles) and also administers it.
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code=ROLE_OWNER))
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code=ROLE_BUSINESS_ADMIN))
    for channel, status in [("whatsapp", "not_connected"), ("telegram", "not_connected"), ("email", "future"), ("instagram", "future"), ("facebook", "future"), ("web_chat", "future")]:
        db.add(ChannelConfig(tenant_id=tenant.id, channel_type=channel, status=status, public_config_json={"enabled": channel == "whatsapp"}))
    ensure_chatbot(db, tenant)
    token = issue_user_token(db, user, PURPOSE_VERIFY_EMAIL, VERIFY_EMAIL_TTL)
    db.commit()
    send_account_email(verification_email(user.email, token))
    return start_session(db, request, response, user, tenant.slug)

@router.post("/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce_rate_limit(
        f"auth:login:{client_ip(request)}:{normalized_identifier(payload.email)}",
        max_requests=LOGIN_RATE_LIMIT_MAX,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    user = db.query(User).filter(User.email == str(payload.email).lower()).first()
    ok, upgraded_hash = verify_and_upgrade(payload.password, user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if upgraded_hash:
        # Older bcrypt hashes become Argon2id the first time the right password is seen.
        user.password_hash = upgraded_hash
    slug = resolve_login_tenant_slug(payload.tenant_slug, memberships(db, user))
    return start_session(db, request, response, user, slug)

@router.post("/logout")
def logout(response: Response, payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)):
    revoke_session(db, payload["session"])
    db.commit()
    clear_session_cookie(response)
    return {"status": "signed_out"}

@router.get("/me")
def me(user: User = Depends(get_current_user), payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)):
    session_row = payload["session"]
    return {
        **user_summary(user),
        "memberships": memberships(db, user),
        "tenant_slug": session_row.tenant_slug,
        "csrf_token": csrf_token_for(session_row.token_hash),
    }

@router.post("/verify-email")
def verify_email(payload: TokenRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"auth:verify:{client_ip(request)}", max_requests=20, window_seconds=3600)
    row = consume_user_token(db, payload.token, PURPOSE_VERIFY_EMAIL)
    user = db.get(User, row.user_id)
    if user and user.email_verified_at is None:
        user.email_verified_at = utcnow()
    db.commit()
    return {"status": "verified"}

@router.post("/verify-email/resend")
def resend_verification(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(f"auth:verify-resend:{user.id}", max_requests=EMAIL_LINK_RATE_LIMIT_MAX, window_seconds=EMAIL_LINK_RATE_LIMIT_WINDOW_SECONDS)
    if user.email_verified_at is not None:
        return {"status": "already_verified"}
    token = issue_user_token(db, user, PURPOSE_VERIFY_EMAIL, VERIFY_EMAIL_TTL)
    db.commit()
    send_account_email(verification_email(user.email, token))
    return {"status": "sent"}

@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    enforce_rate_limit(f"auth:reset:{client_ip(request)}", max_requests=10, window_seconds=3600)
    enforce_rate_limit(f"auth:reset-email:{normalized_identifier(email)}", max_requests=EMAIL_LINK_RATE_LIMIT_MAX, window_seconds=EMAIL_LINK_RATE_LIMIT_WINDOW_SECONDS)
    user = db.query(User).filter(User.email == email).first()
    if user and user.is_active:
        token = issue_user_token(db, user, PURPOSE_PASSWORD_RESET, PASSWORD_RESET_TTL)
        db.commit()
        send_account_email(password_reset_email(user.email, token))
    # Same answer whether or not the address has an account, so it cannot be used to find accounts.
    return {"status": "sent_if_account_exists"}

@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirm, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"auth:reset-confirm:{client_ip(request)}", max_requests=20, window_seconds=3600)
    row = consume_user_token(db, payload.token, PURPOSE_PASSWORD_RESET)
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired. Ask for a new one.")
    user.password_hash = hash_password(payload.new_password)
    # Reading the email proves the address, and every signed-in browser must sign in again.
    user.email_verified_at = user.email_verified_at or utcnow()
    revoke_all_sessions(db, user.id)
    db.commit()
    return {"status": "password_changed"}

@router.post("/invites/accept", response_model=SessionResponse)
def accept_invite(payload: InviteAccept, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce_rate_limit(f"auth:invite:{client_ip(request)}", max_requests=20, window_seconds=3600)
    invite = db.query(TenantInvite).filter(TenantInvite.token_hash == hash_token(payload.token)).first()
    if invite is None or invite.accepted_at or invite.revoked_at or utcnow() >= aware(invite.expires_at):
        raise HTTPException(status_code=400, detail="This invitation is invalid or has expired. Ask for a new one.")
    tenant = db.get(Tenant, invite.tenant_id)
    user = db.query(User).filter(User.email == invite.email).first()
    if user:
        # An existing account joins only with its own password.
        ok, upgraded_hash = verify_and_upgrade(payload.password, user.password_hash)
        if not ok or not user.is_active:
            raise HTTPException(status_code=401, detail="Use the password of your existing account to accept.")
        if upgraded_hash:
            user.password_hash = upgraded_hash
    else:
        if not payload.full_name:
            raise HTTPException(status_code=422, detail="Enter your name to create your account.")
        user = User(email=invite.email, full_name=payload.full_name, password_hash=hash_password(payload.password))
        db.add(user)
        db.flush()
    # The invitation reached this inbox, so the address is confirmed.
    user.email_verified_at = user.email_verified_at or utcnow()
    exists = db.query(TenantUserRole).filter(TenantUserRole.tenant_id == invite.tenant_id, TenantUserRole.user_id == user.id, TenantUserRole.role_code == invite.role_code).first()
    if exists:
        exists.is_active = True
    else:
        db.add(TenantUserRole(tenant_id=invite.tenant_id, user_id=user.id, role_code=invite.role_code))
    invite.accepted_at = utcnow()
    db.add(AuditLog(tenant_id=invite.tenant_id, actor_user_id=user.id, action="team.invite_accepted", entity_type="tenant_invite", entity_id=str(invite.id), details_json={"role_code": invite.role_code}))
    db.flush()
    return start_session(db, request, response, user, tenant.slug if tenant else None)


@router.delete("/account")
def delete_account(
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    ctx: dict = Depends(require_tenant_roles(ROLE_OWNER)),
):
    if user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admins cannot use self-serve account deletion")

    roles = ctx.get("roles", [])
    if ROLE_OWNER not in roles:
        raise HTTPException(status_code=403, detail="Only the workspace owner can delete this account")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    brand = db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant.id).first()
    if brand:
        delete_local_logo_file(brand.logo_url)

    # Must see the user's other workspaces, which row-level security hides in a tenant request.
    with system_scope(db):
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
    db.query(TenantInvite).filter(TenantInvite.tenant_id == tenant.id).delete()
    db.query(Chatbot).filter(Chatbot.tenant_id == tenant.id).delete()
    db.delete(tenant)
    if remaining_memberships == 0:
        revoke_all_sessions(db, user.id)
        db.delete(user)
    db.commit()

    return {
        "status": "deleted",
        "deleted_tenant": deleted_tenant,
        "deleted_user": remaining_memberships == 0,
    }
