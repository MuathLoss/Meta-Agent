from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.entities import Branch, BusinessSetting, ChannelConfig, FaqItem, IntentDefinition, RoutingRule, Tenant, TenantBrand, TenantUserRole


BOT_INTENTS = {
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


def normalize_intent_code(code: str) -> str:
    return code.strip().upper().replace(" ", "_").replace("-", "_")


def default_routing_payload(intent: IntentDefinition) -> dict:
    code = normalize_intent_code(intent.code)

    if code == "COMPLAINT":
        return {
            "intent_code": code,
            "primary_owner_role": "OPERATIONS_STAFF",
            "notify_roles_json": [],
            "escalation_json": {},
            "handoff_required": True,
            "ticket_type": "complaint",
            "priority": "high",
        }

    if code in {"HUMAN_REQUEST", "RESERVATION", "BOOKING"}:
        return {
            "intent_code": code,
            "primary_owner_role": "OPERATIONS_STAFF",
            "notify_roles_json": [],
            "escalation_json": {},
            "handoff_required": True,
            "ticket_type": "handoff",
            "priority": "normal",
        }

    if code == "PAYMENT_TRANSFER":
        return {
            "intent_code": code,
            "primary_owner_role": "FINANCE",
            "notify_roles_json": ["OPERATIONS_STAFF"],
            "escalation_json": {},
            "handoff_required": True,
            "ticket_type": "payment",
            "priority": "normal",
        }

    if code == "CERTIFICATES":
        return {
            "intent_code": code,
            "primary_owner_role": "CERTIFICATES",
            "notify_roles_json": ["OPERATIONS_STAFF"],
            "escalation_json": {},
            "handoff_required": True,
            "ticket_type": "certificate",
            "priority": "normal",
        }

    if code == "UNKNOWN":
        return {
            "intent_code": code,
            "primary_owner_role": "OPERATIONS_STAFF",
            "notify_roles_json": [],
            "escalation_json": {"fallback": True, "policy": "clarify_once_then_handoff"},
            "handoff_required": False,
            "ticket_type": None,
            "priority": "normal",
        }

    if code in BOT_INTENTS or intent.default_response_topic_key:
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
        "primary_owner_role": "OPERATIONS_STAFF",
        "notify_roles_json": [],
        "escalation_json": {"reason": "custom_intent_without_default_response"},
        "handoff_required": True,
        "ticket_type": "handoff",
        "priority": "normal",
    }


class OnboardingService:
    def save_step(self, db: Session, tenant: Tenant, step: int, data: dict) -> dict:
        row = db.query(BusinessSetting).filter(BusinessSetting.tenant_id == tenant.id, BusinessSetting.key == f"onboarding_step_{step}").first()
        if not row:
            row = BusinessSetting(tenant_id=tenant.id, key=f"onboarding_step_{step}", value_json={})
            db.add(row)
        row.value_json = data
        if step == 1:
            tenant.display_name = data.get("display_name") or data.get("business_name") or tenant.display_name
            tenant.timezone = data.get("timezone") or tenant.timezone
            tenant.default_lang = data.get("default_lang") or tenant.default_lang
        db.commit()
        return {"saved": True, "step": step}

    def ensure_default_routing_rules(self, db: Session, tenant: Tenant) -> int:
        intents = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.enabled.is_(True)).all()
        created = 0
        for intent in intents:
            code = normalize_intent_code(intent.code)
            intent.code = code
            exists = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == code).first()
            if exists:
                continue
            db.add(RoutingRule(tenant_id=tenant.id, **default_routing_payload(intent)))
            created += 1
        if created:
            db.commit()
        return created

    def readiness(self, db: Session, tenant: Tenant) -> dict:
        branch_count = db.query(func.count(Branch.id)).filter(Branch.tenant_id == tenant.id, Branch.is_active.is_(True)).scalar() or 0
        admin_count = db.query(func.count(TenantUserRole.id)).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.role_code == "BUSINESS_ADMIN", TenantUserRole.is_active.is_(True)).scalar() or 0
        ops_count = db.query(func.count(TenantUserRole.id)).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.role_code.in_(["BUSINESS_ADMIN", "OPERATIONS_STAFF"]), TenantUserRole.is_active.is_(True)).scalar() or 0
        faq_count = db.query(func.count(FaqItem.id)).filter(FaqItem.tenant_id == tenant.id, FaqItem.status == "active").scalar() or 0
        intents = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.enabled.is_(True)).all()
        routes = {r.intent_code for r in db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id).all()}
        missing = [normalize_intent_code(i.code) for i in intents if normalize_intent_code(i.code) not in routes]
        brand = db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant.id).first()
        from app.services.channel_health_service import readiness as channel_readiness
        channels = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id).all()
        channel_ready = any(channel_readiness(row).get("ready") for row in channels)
        items = [
            {"key": "business_profile", "label": "Business profile and brand exist", "passed": bool(tenant.display_name and tenant.timezone and tenant.default_lang and brand)},
            {"key": "branches", "label": "At least one branch exists", "passed": branch_count > 0},
            {"key": "staff_roles", "label": "Business admin and operations user exist", "passed": admin_count > 0 and ops_count > 0},
            {"key": "faq", "label": "Active FAQ content exists", "passed": faq_count > 0},
            {"key": "intents", "label": "Enabled intents exist", "passed": len(intents) > 0},
            {"key": "routing", "label": "Every enabled intent has routing", "passed": len(intents) > 0 and not missing, "detail": ", ".join(missing) if missing else None},
            {"key": "channel", "label": "At least one channel has its required details and is enabled", "passed": channel_ready},
        ]
        return {"is_ready": all(i["passed"] for i in items), "items": items}

    def publish(self, db: Session, tenant: Tenant) -> dict:
        result = self.readiness(db, tenant)
        if result["is_ready"]:
            tenant.status = "active"
            db.commit()
        return {"published": result["is_ready"], **result}
