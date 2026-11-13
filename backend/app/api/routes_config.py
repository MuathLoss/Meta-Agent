from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import hash_password
from app.core.tenancy import (
    ROLE_BROADCAST_OPERATOR,
    ROLE_BUSINESS_ADMIN,
    ROLE_CERTIFICATES,
    ROLE_FINANCE,
    ROLE_OPERATIONS_STAFF,
    ROLE_SUPERVISOR,
    get_current_tenant,
    require_tenant_roles,
)
from app.models.entities import (
    AuditLog,
    Branch,
    BusinessSetting,
    FaqItem,
    IntentDefinition,
    IntentKeyword,
    RoutingRule,
    Tenant,
    TenantBrand,
    TenantUserRole,
    TrainingExample,
    User,
)

router = APIRouter(tags=["tenant configuration"])
ADMIN_ROLES = (ROLE_BUSINESS_ADMIN,)
STAFF_ROLES = (
    ROLE_BUSINESS_ADMIN,
    ROLE_OPERATIONS_STAFF,
    ROLE_FINANCE,
    ROLE_CERTIFICATES,
    ROLE_SUPERVISOR,
    ROLE_BROADCAST_OPERATOR,
)
UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "tenant_logos"
MAX_LOGO_BYTES = 5 * 1024 * 1024
ALLOWED_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def audit(db: Session, tenant_id: int, actor_id: int | None, action: str, entity_type: str, entity_id: str | None, details: dict | None = None) -> None:
    db.add(AuditLog(tenant_id=tenant_id, actor_user_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, details_json=details or {}))


def is_tenant_member(db: Session, tenant_id: int, user_id: int) -> bool:
    return db.query(TenantUserRole.id).filter(TenantUserRole.tenant_id == tenant_id, TenantUserRole.user_id == user_id).first() is not None


def is_member_of_another_tenant(db: Session, tenant_id: int, user_id: int) -> bool:
    return db.query(TenantUserRole.id).filter(TenantUserRole.tenant_id != tenant_id, TenantUserRole.user_id == user_id).first() is not None


def ensure_brand(db: Session, tenant_id: int) -> TenantBrand:
    brand = db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant_id).first()
    if not brand:
        brand = TenantBrand(tenant_id=tenant_id)
        db.add(brand)
        db.flush()
    return brand


def delete_local_logo_file(logo_url: str | None) -> None:
    if not logo_url or not logo_url.startswith("/uploads/tenant_logos/"):
        return
    relative_path = logo_url.removeprefix("/uploads/")
    file_path = Path(__file__).resolve().parents[2] / "uploads" / relative_path
    if file_path.exists() and file_path.is_file():
        file_path.unlink()


def _svg_or_xml_like(content: bytes) -> bool:
    stripped = content[:512].lstrip().lower()
    return stripped.startswith((b"<svg", b"<?xml", b"<!doctype svg")) or b"<svg" in stripped


def detect_logo_type(content: bytes) -> tuple[str, str] | None:
    if _svg_or_xml_like(content):
        return None
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _has_svg_filename(filename: str | None) -> bool:
    return Path(filename or "").suffix.lower() == ".svg"


def validate_profile_logo_url(logo_url: str | None) -> str | None:
    if logo_url is None:
        return None
    value = logo_url.strip()
    if value == "":
        return ""
    lowered = value.lower()
    if lowered.startswith(("data:", "javascript:", "http://", "https://", "//")):
        raise HTTPException(status_code=400, detail="Unsupported logo URL")
    if "\\" in value or "\x00" in value:
        raise HTTPException(status_code=400, detail="Unsupported logo URL")
    if not value.startswith("/uploads/tenant_logos/"):
        raise HTTPException(status_code=400, detail="Unsupported logo URL")
    decoded = unquote(value)
    parts = decoded.split("/")
    if ".." in parts or any(part == "" for part in parts[1:]):
        raise HTTPException(status_code=400, detail="Unsupported logo URL")
    extension = Path(decoded).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Unsupported logo URL")
    return value


def normalize_intent_code(code: str) -> str:
    return code.strip().upper().replace(" ", "_").replace("-", "_")


def normalize_topic_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


AUTO_HANDOFF_REASON = "custom_intent_without_default_response"


def intent_has_custom_response(intent: IntentDefinition) -> bool:
    if (intent.response_mode or "").lower() != "custom":
        return False
    return bool((intent.custom_response_ar or "").strip() or (intent.custom_response_en or "").strip())


def default_routing_payload(intent_code: str, default_response_topic_key: str | None = None, has_custom_response: bool = False) -> dict:
    code = normalize_intent_code(intent_code)

    bot_intents = {
        "GREETING",
        "FAQ_GENERAL",
        "LOCATION",
        "SCHEDULES",
        "PRICING",
        "DELIVERY",
        "DISCOUNTS_OFFERS",
        "WOMENS_SECTION",
        "KIDS_SECTION",
        "ACCREDITATION",
        "STEP_PREP",
        "BEGINNER_ENGLISH",
    }

    handoff_intents = {
        "HUMAN_REQUEST": {"ticket_type": "handoff", "priority": "normal"},
        "RESERVATION": {"ticket_type": "handoff", "priority": "normal"},
        "BOOKING": {"ticket_type": "handoff", "priority": "normal"},
        "PAYMENT_TRANSFER": {"ticket_type": "payment", "priority": "normal", "primary_owner_role": ROLE_FINANCE, "notify_roles_json": [ROLE_OPERATIONS_STAFF]},
        "CERTIFICATES": {"ticket_type": "certificate", "priority": "normal", "primary_owner_role": ROLE_CERTIFICATES, "notify_roles_json": [ROLE_OPERATIONS_STAFF]},
        "COMPLAINT": {"ticket_type": "complaint", "priority": "high"},
    }

    if code in handoff_intents:
        data = handoff_intents[code]
        return {
            "intent_code": code,
            "primary_owner_role": data.get("primary_owner_role", ROLE_OPERATIONS_STAFF),
            "notify_roles_json": data.get("notify_roles_json", []),
            "escalation_json": {},
            "handoff_required": True,
            "ticket_type": data["ticket_type"],
            "priority": data["priority"],
        }

    if code == "UNKNOWN":
        return {
            "intent_code": code,
            "primary_owner_role": ROLE_OPERATIONS_STAFF,
            "notify_roles_json": [],
            "escalation_json": {"fallback": True, "policy": "clarify_once_then_handoff"},
            "handoff_required": False,
            "ticket_type": None,
            "priority": "normal",
        }

    # A topic with its own written answer is answered by the agent, like a topic
    # that points at an approved answer. Protected handoff topics are decided above.
    if code in bot_intents or default_response_topic_key or has_custom_response:
        return {
            "intent_code": code,
            "primary_owner_role": "BOT",
            "notify_roles_json": [],
            "escalation_json": {},
            "handoff_required": False,
            "ticket_type": None,
            "priority": "normal",
        }

    return {
        "intent_code": code,
        "primary_owner_role": ROLE_OPERATIONS_STAFF,
        "notify_roles_json": [],
        "escalation_json": {"reason": AUTO_HANDOFF_REASON},
        "handoff_required": True,
        "ticket_type": "handoff",
        "priority": "normal",
    }


def ensure_routing_rule_for_intent(db: Session, tenant_id: int, intent: IntentDefinition, actor_id: int | None = None, *, correct_untouched_default: bool = False) -> RoutingRule | None:
    if not intent.enabled:
        return None
    code = normalize_intent_code(intent.code)
    has_custom_response = intent_has_custom_response(intent)
    existing = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant_id, RoutingRule.intent_code == code).first()
    if existing:
        # Earlier versions sent every topic with a written answer to staff without
        # replying. Correct that only while the rule is still the automatic default;
        # a rule an admin saved carries their own choices and is left alone.
        untouched_default = (existing.escalation_json or {}) == {"reason": AUTO_HANDOFF_REASON}
        if correct_untouched_default and has_custom_response and untouched_default:
            data = default_routing_payload(code, intent.default_response_topic_key, has_custom_response)
            for key, value in data.items():
                setattr(existing, key, value)
            audit(db, tenant_id, actor_id, "routing_rule.auto_corrected", "routing_rule", code, data)
        return existing
    data = default_routing_payload(code, intent.default_response_topic_key, has_custom_response)
    row = RoutingRule(tenant_id=tenant_id, **data)
    db.add(row)
    db.flush()
    audit(db, tenant_id, actor_id, "routing_rule.auto_created", "routing_rule", code, data)
    return row


def ensure_routing_rules_for_enabled_intents(db: Session, tenant_id: int, actor_id: int | None = None) -> int:
    intents = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant_id, IntentDefinition.enabled.is_(True)).all()
    created = 0
    for intent in intents:
        before = db.query(RoutingRule.id).filter(RoutingRule.tenant_id == tenant_id, RoutingRule.intent_code == normalize_intent_code(intent.code)).first()
        ensure_routing_rule_for_intent(db, tenant_id, intent, actor_id)
        if before is None:
            created += 1
    return created


class TenantProfileUpdate(BaseModel):
    display_name: str | None = None
    legal_name: str | None = None
    country: str | None = None
    timezone: str | None = None
    default_lang: str | None = None
    logo_url: str | None = None
    primary_color: str | None = None
    support_email: EmailStr | None = None
    support_phone: str | None = None


class SettingUpsert(BaseModel):
    key: str
    value_json: dict = Field(default_factory=dict)


class BranchCreate(BaseModel):
    name: str
    address: str | None = None
    city: str | None = None
    maps_url: str | None = None
    hours_json: dict = Field(default_factory=dict)
    is_active: bool = True


class BranchUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    maps_url: str | None = None
    hours_json: dict | None = None
    is_active: bool | None = None


class StaffCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8)
    roles: list[str] = Field(default_factory=lambda: [ROLE_OPERATIONS_STAFF])


class StaffRoleUpdate(BaseModel):
    roles: list[str]
    is_active: bool = True


class FaqCreate(BaseModel):
    topic_key: str
    question_ar: str | None = None
    english_question: str | None = None
    arabic_answer: str
    english_answer: str | None = None
    status: str = "active"


class FaqUpdate(BaseModel):
    topic_key: str | None = None
    question_ar: str | None = None
    english_question: str | None = None
    arabic_answer: str | None = None
    english_answer: str | None = None
    status: str | None = None


class IntentCreate(BaseModel):
    code: str
    label: str
    is_universal: bool = False
    enabled: bool = True
    supported_languages: str = "ar"
    response_mode: str = "faq"
    default_response_topic_key: str | None = None
    custom_response_ar: str | None = None
    custom_response_en: str | None = None


class IntentUpdate(BaseModel):
    label: str | None = None
    is_universal: bool | None = None
    enabled: bool | None = None
    supported_languages: str | None = None
    response_mode: str | None = None
    default_response_topic_key: str | None = None
    custom_response_ar: str | None = None
    custom_response_en: str | None = None


class KeywordCreate(BaseModel):
    intent_code: str
    phrase: str
    weight: int = 1
    lang: str = "ar"


class RoutingRuleUpsert(BaseModel):
    intent_code: str
    primary_owner_role: str = "BOT"
    notify_roles_json: list[str] = Field(default_factory=list)
    escalation_json: dict = Field(default_factory=dict)
    handoff_required: bool = False
    ticket_type: str | None = None
    priority: str = "normal"
    response_behavior: str = "normal"
    followup_question_ar: str | None = None
    followup_question_en: str | None = None


class TrainingExampleCreate(BaseModel):
    raw_text: str
    labeled_intent: str | None = None
    source: str = "manual"


@router.get("/tenants/current")
def current_tenant(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    brand = db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant.id).first()
    roles = ctx.get("roles", [])
    return {
        "id": tenant.id,
        "slug": tenant.slug,
        "display_name": tenant.display_name,
        "legal_name": tenant.legal_name,
        "country": tenant.country,
        "timezone": tenant.timezone,
        "default_lang": tenant.default_lang,
        "status": tenant.status,
        "roles": roles,
        "brand": {
            "logo_url": brand.logo_url if brand else None,
            "primary_color": brand.primary_color if brand else "#5b0f20",
            "support_email": brand.support_email if brand else None,
            "support_phone": brand.support_phone if brand else None,
        },
    }


@router.put("/settings/profile")
def update_profile(payload: TenantProfileUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    for field in ["display_name", "legal_name", "country", "timezone", "default_lang"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(tenant, field, value)
    brand = ensure_brand(db, tenant.id)
    for field in ["logo_url", "primary_color", "support_email", "support_phone"]:
        value = getattr(payload, field)
        if value is not None or field == "logo_url" and "logo_url" in payload.model_fields_set:
            if field == "logo_url":
                value = validate_profile_logo_url(value)
            if field == "logo_url" and value in {"", None}:
                delete_local_logo_file(brand.logo_url)
            setattr(brand, field, str(value) if value is not None else None)
    audit(db, tenant.id, ctx["user"].id, "settings.profile.updated", "tenant", str(tenant.id), payload.model_dump(exclude_none=True))
    db.commit()
    return {"status": "updated"}


@router.post("/settings/profile/logo")
async def upload_profile_logo(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES)),
):
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_LOGO_TYPES or _has_svg_filename(file.filename):
        raise HTTPException(status_code=400, detail="Unsupported image format")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Please keep the image under 5 MB")
    detected = detect_logo_type(content)
    if not detected:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    detected_content_type, extension = detected
    if content_type != detected_content_type:
        raise HTTPException(status_code=400, detail="Unsupported image format")

    brand = ensure_brand(db, tenant.id)
    tenant_dir = UPLOAD_ROOT / tenant.slug
    tenant_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    file_path = tenant_dir / filename
    file_path.write_bytes(content)

    delete_local_logo_file(brand.logo_url)
    logo_url = f"/uploads/tenant_logos/{tenant.slug}/{filename}"
    brand.logo_url = logo_url
    audit(db, tenant.id, ctx["user"].id, "settings.profile.logo_uploaded", "tenant", str(tenant.id), {"logo_url": logo_url, "stored_filename": filename})
    db.commit()
    # Same relative form as the saved profile, so it works behind any proxy or domain.
    return {"status": "uploaded", "logo_url": logo_url}


@router.get("/settings/business")
def list_settings(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    rows = db.query(BusinessSetting).filter(BusinessSetting.tenant_id == tenant.id).order_by(BusinessSetting.key).all()
    return [{"id": r.id, "key": r.key, "value_json": r.value_json or {}} for r in rows]


@router.put("/settings/business/{key}")
def upsert_setting(key: str, payload: SettingUpsert, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(BusinessSetting).filter(BusinessSetting.tenant_id == tenant.id, BusinessSetting.key == key).first()
    if not row:
        row = BusinessSetting(tenant_id=tenant.id, key=key, value_json=payload.value_json)
        db.add(row)
    else:
        row.value_json = payload.value_json
    audit(db, tenant.id, ctx["user"].id, "settings.business.upserted", "business_setting", key, {"value_json": payload.value_json})
    db.commit()
    return {"status": "saved", "key": key}


@router.get("/branches")
def list_branches(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    rows = db.query(Branch).filter(Branch.tenant_id == tenant.id).order_by(Branch.created_at.desc()).all()
    return [{"id": r.id, "name": r.name, "address": r.address, "city": r.city, "maps_url": r.maps_url, "hours_json": r.hours_json or {}, "is_active": r.is_active} for r in rows]


@router.post("/branches")
def create_branch(payload: BranchCreate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = Branch(tenant_id=tenant.id, **payload.model_dump())
    db.add(row); db.flush()
    audit(db, tenant.id, ctx["user"].id, "branch.created", "branch", str(row.id), payload.model_dump())
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": "created"}


@router.put("/branches/{branch_id}")
def update_branch(branch_id: int, payload: BranchUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(Branch).filter(Branch.tenant_id == tenant.id, Branch.id == branch_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    audit(db, tenant.id, ctx["user"].id, "branch.updated", "branch", str(row.id), payload.model_dump(exclude_none=True))
    db.commit()
    return {"status": "updated"}


@router.delete("/branches/{branch_id}")
def delete_branch(branch_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(Branch).filter(Branch.tenant_id == tenant.id, Branch.id == branch_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    audit(db, tenant.id, ctx["user"].id, "branch.deleted", "branch", str(row.id), {"name": row.name})
    db.delete(row)
    db.commit()
    return {"status": "deleted", "branch_id": branch_id}


@router.get("/staff")
def list_staff(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    rows = db.query(User, TenantUserRole).join(TenantUserRole, TenantUserRole.user_id == User.id).filter(TenantUserRole.tenant_id == tenant.id).order_by(User.email).all()
    users: dict[int, dict] = {}
    for user, role in rows:
        users.setdefault(user.id, {"id": user.id, "email": user.email, "full_name": user.full_name, "is_active": user.is_active, "roles": []})["roles"].append(role.role_code)
    return list(users.values())


@router.post("/staff")
def create_staff(payload: StaffCreate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    allowed = set(STAFF_ROLES)
    if not set(payload.roles).issubset(allowed):
        raise HTTPException(status_code=400, detail="Unknown role in request")
    user = db.query(User).filter(User.email == str(payload.email).lower()).first()
    if not user:
        user = User(email=str(payload.email).lower(), full_name=payload.full_name, password_hash=hash_password(payload.password), is_platform_admin=False)
        db.add(user); db.flush()
    else:
        # An existing account belongs to its owner. Until there is an invitation
        # the person accepts, another workspace must not attach or rename it.
        if user.is_platform_admin or not is_tenant_member(db, tenant.id, user.id):
            raise HTTPException(status_code=409, detail="This email address already has an account. Use a different email address.")
        if payload.full_name and not is_member_of_another_tenant(db, tenant.id, user.id):
            user.full_name = payload.full_name
    for role in dict.fromkeys(payload.roles):
        exists = db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == user.id, TenantUserRole.role_code == role).first()
        if not exists:
            db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code=role, is_active=True))
        else:
            exists.is_active = True
    audit(db, tenant.id, ctx["user"].id, "staff.created_or_updated", "user", str(user.id), {"roles": payload.roles})
    db.commit(); db.refresh(user)
    return {"id": user.id, "status": "saved"}


@router.put("/staff/{user_id}/roles")
def replace_staff_roles(user_id: int, payload: StaffRoleUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    if not set(payload.roles).issubset(set(STAFF_ROLES)):
        raise HTTPException(status_code=400, detail="Unknown role in request")
    # Roles can only be changed for people who already belong to this workspace.
    if not db.get(User, user_id) or not is_tenant_member(db, tenant.id, user_id):
        raise HTTPException(status_code=404, detail="Staff member not found for this tenant")
    db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == user_id).delete()
    for role in dict.fromkeys(payload.roles):
        db.add(TenantUserRole(tenant_id=tenant.id, user_id=user_id, role_code=role, is_active=payload.is_active))
    audit(db, tenant.id, ctx["user"].id, "staff.roles.replaced", "user", str(user_id), payload.model_dump())
    db.commit()
    return {"status": "updated"}


@router.delete("/staff/{user_id}")
def delete_staff(user_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    deleted = db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == user_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Staff member not found for this tenant")
    audit(db, tenant.id, ctx["user"].id, "staff.deleted", "user", str(user_id), {"email": user.email})
    db.commit()
    return {"status": "deleted", "user_id": user_id}


@router.get("/faq")
def list_faq(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    rows = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id).order_by(FaqItem.topic_key).all()
    return [{"id": r.id, "topic_key": r.topic_key, "question_ar": r.question_ar, "english_question": r.english_question, "arabic_answer": r.arabic_answer, "english_answer": r.english_answer, "status": r.status} for r in rows]


@router.post("/faq")
def create_faq(payload: FaqCreate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = FaqItem(tenant_id=tenant.id, **payload.model_dump())
    db.add(row); db.flush()
    audit(db, tenant.id, ctx["user"].id, "faq.created", "faq_item", str(row.id), {"topic_key": row.topic_key})
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": "created"}


@router.put("/faq/{faq_id}")
def update_faq(faq_id: int, payload: FaqUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.id == faq_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="FAQ not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    audit(db, tenant.id, ctx["user"].id, "faq.updated", "faq_item", str(row.id), payload.model_dump(exclude_none=True))
    db.commit()
    return {"status": "updated"}


@router.delete("/faq/{faq_id}")
def archive_faq(faq_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.id == faq_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="FAQ not found")
    row.status = "archived"
    audit(db, tenant.id, ctx["user"].id, "faq.archived", "faq_item", str(row.id), {})
    db.commit()
    return {"status": "archived"}


@router.delete("/faq/{faq_id}/permanent")
def delete_faq_permanently(faq_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.id == faq_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="FAQ not found")
    topic_key = row.topic_key
    db.delete(row)
    audit(db, tenant.id, ctx["user"].id, "faq.deleted", "faq_item", str(faq_id), {"topic_key": topic_key})
    db.commit()
    return {"status": "deleted", "faq_id": faq_id}


@router.get("/intents")
def list_intents(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    intents = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id).order_by(IntentDefinition.code).all()
    keywords = db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id).all()
    by_intent: dict[str, list[dict]] = {}
    for k in keywords:
        by_intent.setdefault(k.intent_code, []).append({"id": k.id, "phrase": k.phrase, "weight": k.weight, "lang": k.lang})
    return [{
        "id": i.id,
        "code": i.code,
        "label": i.label,
        "is_universal": i.is_universal,
        "enabled": i.enabled,
        "supported_languages": i.supported_languages,
        "response_mode": i.response_mode,
        "default_response_topic_key": i.default_response_topic_key,
        "custom_response_ar": i.custom_response_ar,
        "custom_response_en": i.custom_response_en,
        "keywords": by_intent.get(i.code, []),
    } for i in intents]


@router.post("/intents")
def create_intent(payload: IntentCreate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    code = normalize_intent_code(payload.code)
    exists = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == code).first()
    if exists:
        raise HTTPException(status_code=409, detail="Intent code already exists")
    data = payload.model_dump()
    data["code"] = code
    data["supported_languages"] = (payload.supported_languages or "ar").lower()
    data["response_mode"] = (payload.response_mode or "faq").lower()
    if data["response_mode"] not in {"faq", "custom", "business_settings"}:
        raise HTTPException(status_code=400, detail="Unsupported response_mode")
    if data["response_mode"] == "custom" and not (payload.custom_response_ar or payload.custom_response_en):
        raise HTTPException(status_code=400, detail="Custom response requires Arabic or English response text")
    if data["response_mode"] in {"faq", "business_settings"}:
        data["custom_response_ar"] = None
        data["custom_response_en"] = None
    row = IntentDefinition(tenant_id=tenant.id, **data)
    db.add(row); db.flush()
    ensure_routing_rule_for_intent(db, tenant.id, row, ctx["user"].id)
    audit(db, tenant.id, ctx["user"].id, "intent.created", "intent_definition", str(row.id), {"code": row.code})
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": "created", "routing_rule_created": True}


@router.put("/intents/{intent_id}")
def update_intent(intent_id: int, payload: IntentUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.id == intent_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Intent not found")
    data = payload.model_dump(exclude_none=True)
    if "supported_languages" in data:
        data["supported_languages"] = str(data["supported_languages"]).lower()
    if "response_mode" in data:
        data["response_mode"] = str(data["response_mode"]).lower()
        if data["response_mode"] not in {"faq", "custom", "business_settings"}:
            raise HTTPException(status_code=400, detail="Unsupported response_mode")
    for k, v in data.items():
        setattr(row, k, v)
    row.code = normalize_intent_code(row.code)
    if row.response_mode == "custom" and not (row.custom_response_ar or row.custom_response_en):
        raise HTTPException(status_code=400, detail="Custom response requires Arabic or English response text")
    if row.response_mode in {"faq", "business_settings"}:
        row.custom_response_ar = None
        row.custom_response_en = None
    if row.enabled:
        ensure_routing_rule_for_intent(db, tenant.id, row, ctx["user"].id, correct_untouched_default=True)
    audit(db, tenant.id, ctx["user"].id, "intent.updated", "intent_definition", str(row.id), data)
    db.commit()
    return {"status": "updated"}


@router.delete("/intents/{intent_id}")
def delete_intent(intent_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.id == intent_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Intent not found")
    code = row.code
    db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.intent_code == code).delete()
    db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == code).delete()
    db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id, TrainingExample.labeled_intent == code).delete()
    db.delete(row)
    audit(db, tenant.id, ctx["user"].id, "intent.deleted", "intent_definition", str(intent_id), {"code": code})
    db.commit()
    return {"status": "deleted", "intent_id": intent_id}


@router.delete("/knowledge-items/{intent_code}")
def delete_knowledge_item(intent_code: str, topic_key: str | None = None, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    code = normalize_intent_code(intent_code)
    normalized_topic_key = normalize_topic_key(topic_key) if topic_key else None

    intent_ids = [row.id for row in db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == code).all()]
    deleted_keywords = db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.intent_code == code).delete()
    deleted_routes = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == code).delete()
    deleted_examples = db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id, TrainingExample.labeled_intent == code).delete()
    deleted_intents = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == code).delete()

    deleted_faqs = 0
    if normalized_topic_key:
        deleted_faqs = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.topic_key == normalized_topic_key).delete()

    if deleted_intents == 0 and deleted_faqs == 0:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    audit(
        db,
        tenant.id,
        ctx["user"].id,
        "knowledge_item.deleted",
        "knowledge_item",
        code,
        {
            "intent_code": code,
            "topic_key": normalized_topic_key,
            "deleted_intent_ids": intent_ids,
            "deleted_intents": deleted_intents,
            "deleted_keywords": deleted_keywords,
            "deleted_routes": deleted_routes,
            "deleted_examples": deleted_examples,
            "deleted_faqs": deleted_faqs,
        },
    )
    db.commit()
    return {
        "status": "deleted",
        "intent_code": code,
        "topic_key": normalized_topic_key,
        "deleted_intents": deleted_intents,
        "deleted_keywords": deleted_keywords,
        "deleted_routes": deleted_routes,
        "deleted_examples": deleted_examples,
        "deleted_faqs": deleted_faqs,
    }


@router.post("/intent-keywords")
def create_keyword(payload: KeywordCreate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    data = payload.model_dump()
    data["intent_code"] = normalize_intent_code(data["intent_code"])
    intent = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == data["intent_code"]).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent code does not exist for this tenant")
    ensure_routing_rule_for_intent(db, tenant.id, intent, ctx["user"].id)
    row = IntentKeyword(tenant_id=tenant.id, **data)
    db.add(row); db.flush()
    audit(db, tenant.id, ctx["user"].id, "intent.keyword.created", "intent_keyword", str(row.id), data)
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": "created"}


@router.delete("/intent-keywords/{keyword_id}")
def delete_keyword(keyword_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.id == keyword_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Keyword not found")
    db.delete(row)
    audit(db, tenant.id, ctx["user"].id, "intent.keyword.deleted", "intent_keyword", str(keyword_id), {})
    db.commit()
    return {"status": "deleted"}


@router.get("/routing-rules")
def list_routing_rules(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    created = ensure_routing_rules_for_enabled_intents(db, tenant.id, ctx["user"].id)
    if created:
        db.commit()
    rows = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id).order_by(RoutingRule.intent_code).all()
    data = []
    for r in rows:
        escalation = r.escalation_json or {}
        data.append({
            "id": r.id,
            "intent_code": r.intent_code,
            "primary_owner_role": r.primary_owner_role,
            "notify_roles_json": r.notify_roles_json or [],
            "escalation_json": escalation,
            "handoff_required": r.handoff_required,
            "ticket_type": r.ticket_type,
            "priority": r.priority,
            "response_behavior": escalation.get("response_behavior", "immediate_handoff" if r.handoff_required else "normal"),
            "followup_question_ar": escalation.get("followup_question_ar"),
            "followup_question_en": escalation.get("followup_question_en"),
        })
    return data


@router.put("/routing-rules/{intent_code}")
def upsert_routing_rule(intent_code: str, payload: RoutingRuleUpsert, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    code = normalize_intent_code(intent_code)
    intent = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == code).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent code does not exist for this tenant")
    row = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == code).first()
    data = payload.model_dump()
    data["intent_code"] = code
    response_behavior = str(data.pop("response_behavior", "normal") or "normal").lower()
    followup_question_ar = data.pop("followup_question_ar", None)
    followup_question_en = data.pop("followup_question_en", None)
    escalation_json = data.get("escalation_json") or {}
    escalation_json = {
        **escalation_json,
        "response_behavior": response_behavior,
        "followup_question_ar": followup_question_ar,
        "followup_question_en": followup_question_en,
    }
    data["escalation_json"] = escalation_json

    if response_behavior == "normal":
        data["primary_owner_role"] = "BOT"
        data["handoff_required"] = False
        data["ticket_type"] = None
    elif response_behavior == "immediate_handoff":
        if data.get("primary_owner_role") == "BOT":
            data["primary_owner_role"] = ROLE_OPERATIONS_STAFF
        data["handoff_required"] = True
        if not data.get("ticket_type"):
            data["ticket_type"] = "handoff"
    elif response_behavior == "offer_handoff":
        if data.get("primary_owner_role") == "BOT":
            data["primary_owner_role"] = ROLE_OPERATIONS_STAFF
        data["handoff_required"] = False
        if not data.get("ticket_type"):
            data["ticket_type"] = "handoff"
    else:
        raise HTTPException(status_code=400, detail="Unsupported response_behavior")

    if data.get("primary_owner_role") == "BOT":
        data["handoff_required"] = False
        data["ticket_type"] = None
    if response_behavior == "offer_handoff" and not (followup_question_ar or followup_question_en):
        raise HTTPException(status_code=400, detail="Offer handoff requires a follow-up question")
    if data.get("handoff_required") and not data.get("ticket_type"):
        data["ticket_type"] = "handoff"
    if not row:
        row = RoutingRule(tenant_id=tenant.id, **data)
        db.add(row)
    else:
        for k, v in data.items():
            setattr(row, k, v)
    audit(db, tenant.id, ctx["user"].id, "routing_rule.upserted", "routing_rule", code, data)
    db.commit()
    return {"status": "saved"}


@router.post("/routing-rules/backfill-defaults")
def backfill_default_routing_rules(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    created = ensure_routing_rules_for_enabled_intents(db, tenant.id, ctx["user"].id)
    db.commit()
    return {"status": "saved", "created": created}


@router.get("/training-examples")
def list_training_examples(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(*STAFF_ROLES))):
    rows = db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id).order_by(TrainingExample.created_at.desc()).limit(250).all()
    return [{"id": r.id, "raw_text": r.raw_text, "normalized_text": r.normalized_text, "labeled_intent": r.labeled_intent, "source": r.source} for r in rows]


@router.post("/training-examples")
def create_training_example(payload: TrainingExampleCreate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(*ADMIN_ROLES))):
    row = TrainingExample(tenant_id=tenant.id, raw_text=payload.raw_text, normalized_text=payload.raw_text.strip().lower(), labeled_intent=payload.labeled_intent, source=payload.source)
    db.add(row); db.flush()
    audit(db, tenant.id, ctx["user"].id, "training_example.created", "training_example", str(row.id), {"labeled_intent": row.labeled_intent})
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": "created"}
