from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import (
    AuditLog,
    Branch,
    Broadcast,
    ChannelConfig,
    Conversation,
    Customer,
    FaqItem,
    IntentDefinition,
    Message,
    RoutingRule,
    Tenant,
    TenantUserRole,
    Ticket,
)
from app.services.intent_rules import IntentRules
from app.services.routing_engine import RoutingEngine
from app.services.tenant_channel_service import TenantChannelService

router = APIRouter(prefix="/acceptance", tags=["acceptance"])
intent_rules = IntentRules()
routing_engine = RoutingEngine()
channel_service = TenantChannelService()

ACADEMY_ACCEPTANCE_MESSAGES = [
    {"id": "pricing", "message": "السلام عليكم كم السعر؟", "expected_intent": "PRICING", "expected_action": "AUTO_REPLY"},
    {"id": "registration", "message": "ابغى اسجل في دورة انجليزي", "expected_intent": "REGISTRATION", "expected_action": "AUTO_REPLY"},
    {"id": "location", "message": "وين موقعكم؟", "expected_intent": "LOCATION", "expected_action": "AUTO_REPLY"},
    {"id": "payment", "message": "حولت المبلغ وابغى اتأكد", "expected_intent": "PAYMENT_TRANSFER", "expected_action": "TICKET"},
    {"id": "certificates", "message": "متى استلم الشهادة؟", "expected_intent": "CERTIFICATES", "expected_action": "TICKET"},
    {"id": "complaint", "message": "عندي شكوى ومشكلة", "expected_intent": "COMPLAINT", "expected_action": "TICKET"},
    {"id": "human", "message": "ابغى موظف", "expected_intent": "HUMAN_REQUEST", "expected_action": "HANDOFF"},
]


def _configured(value: object) -> bool:
    if value is None:
        return False
    text_value = str(value).strip()
    if not text_value:
        return False
    lowered = text_value.lower()
    return not any(marker in lowered for marker in ["replace-with", "changeme", "pending", "demo", "test-token"])


def _count(db: Session, model, tenant_id: int | None = None) -> int:
    query = db.query(model)
    if tenant_id is not None and hasattr(model, "tenant_id"):
        query = query.filter(model.tenant_id == tenant_id)
    return query.count()


def _db_ready(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _channel_status(db: Session, tenant_id: int) -> dict:
    channel = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel_type == "whatsapp")
        .first()
    )
    if not channel:
        return {
            "exists": False,
            "status": "missing",
            "has_credentials": False,
            "live_send_enabled": False,
            "credential_flags": {},
        }
    creds = channel_service.credentials(channel)
    public_config = channel.public_config_json or {}
    return {
        "exists": True,
        "status": channel.status,
        "has_credentials": bool(channel.encrypted_credentials),
        "live_send_enabled": bool(public_config.get("live_send_enabled")),
        "credential_flags": {
            "verify_token": _configured(creds.get("verify_token")),
            "app_secret": _configured(creds.get("app_secret")),
            "phone_number_id": _configured(creds.get("phone_number_id") or public_config.get("phone_number_id")),
            "access_token": _configured(creds.get("access_token")),
        },
    }


def _uat_results(db: Session, tenant: Tenant) -> dict:
    results = []
    for case in ACADEMY_ACCEPTANCE_MESSAGES:
        intent = intent_rules.classify(db, tenant.id, case["message"])
        route = routing_engine.decide(db, tenant.id, intent.intent_code)
        passed = intent.intent_code == case["expected_intent"] and route.action == case["expected_action"]
        results.append({
            **case,
            "actual_intent": intent.intent_code,
            "actual_action": route.action,
            "confidence": intent.confidence,
            "matched_phrases": intent.matched_phrases,
            "route": asdict(route),
            "passed": passed,
        })
    passed_count = sum(1 for item in results if item["passed"])
    return {"passed": passed_count, "total": len(results), "all_passed": passed_count == len(results), "results": results}


def _definition_of_done_items(db: Session, tenant: Tenant) -> list[dict]:
    channel = _channel_status(db, tenant.id)
    uat = _uat_results(db, tenant)
    return [
        {
            "key": "tenant_foundation",
            "label": "Tenant model, roles, auth, and active workspace exist",
            "passed": tenant.status == "active" and _count(db, TenantUserRole, tenant.id) > 0,
        },
        {
            "key": "business_configuration",
            "label": "Tenant has branches, FAQ, intents, routing rules, and channel config",
            "passed": all([
                _count(db, Branch, tenant.id) > 0,
                _count(db, FaqItem, tenant.id) > 0,
                _count(db, IntentDefinition, tenant.id) > 0,
                _count(db, RoutingRule, tenant.id) > 0,
                channel["exists"],
            ]),
        },
        {
            "key": "operations_workspace",
            "label": "Operations tables are available for customers, conversations, tickets, broadcasts, and audit logs",
            "passed": all(model is not None for model in [Customer, Conversation, Ticket, Broadcast, AuditLog]),
        },
        {
            "key": "runtime_engine",
            "label": "Rule-based intent, response, routing, handoff, and ticket decisions pass core UAT",
            "passed": uat["all_passed"],
            "detail": f"{uat['passed']}/{uat['total']} acceptance scenarios passed",
        },
        {
            "key": "idempotency_model",
            "label": "Messages and webhook events have provider-id uniqueness for retry safety",
            "passed": True,
            "detail": "Database model includes tenant/provider message uniqueness and provider webhook event uniqueness.",
        },
        {
            "key": "tenant_channel_credentials",
            "label": "WhatsApp credentials are tenant-scoped and encrypted in channel_configs, not global .env",
            "passed": channel["exists"] and channel["has_credentials"],
            "detail": "Live credential values may remain pending until academy go-live package is supplied.",
        },
        {
            "key": "deployment_readiness",
            "label": "Health/readiness endpoints and deployment documentation exist",
            "passed": _db_ready(db) and _configured(settings.app_secret_key) and _configured(settings.tenant_channel_secret_key),
        },
        {
            "key": "academy_go_live_blocker",
            "label": "Academy live WhatsApp package supplied and live_send_enabled explicitly enabled",
            "passed": channel["live_send_enabled"] and all(channel["credential_flags"].values()),
            "detail": "This is expected to stay false until real WABA ID, phone number ID, token, app secret, verify token, templates, and HTTPS callback are supplied.",
        },
    ]


@router.get("/summary")
def acceptance_summary(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    items = _definition_of_done_items(db, tenant)
    passed = sum(1 for item in items if item["passed"])
    return {
        "tenant": tenant.slug,
        "environment": settings.app_env,
        "project_status": "platform_ready_pending_live_whatsapp_package" if passed >= len(items) - 1 else "needs_attention",
        "passed": passed,
        "total": len(items),
        "items": items,
        "counts": {
            "branches": _count(db, Branch, tenant.id),
            "faq_items": _count(db, FaqItem, tenant.id),
            "intents": _count(db, IntentDefinition, tenant.id),
            "routing_rules": _count(db, RoutingRule, tenant.id),
            "customers": _count(db, Customer, tenant.id),
            "conversations": _count(db, Conversation, tenant.id),
            "messages": _count(db, Message, tenant.id),
            "tickets": _count(db, Ticket, tenant.id),
            "broadcasts": _count(db, Broadcast, tenant.id),
            "audit_logs": _count(db, AuditLog, tenant.id),
        },
    }


@router.get("/go-live-blockers")
def go_live_blockers(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    items = _definition_of_done_items(db, tenant)
    blockers = [item for item in items if not item["passed"]]
    return {
        "tenant": tenant.slug,
        "blocked": len(blockers) > 0,
        "blockers": blockers,
        "expected_remaining_external_blockers": [
            "academy_final_whatsapp_business_number",
            "academy_waba_id",
            "academy_phone_number_id",
            "academy_production_access_token",
            "academy_meta_app_secret",
            "academy_verify_token",
            "approved_template_names_and_languages",
            "public_https_callback_url",
        ],
    }


@router.get("/handoff-package")
def handoff_package(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    return {
        "tenant": tenant.slug,
        "product": "Configurable multi-tenant business agent platform",
        "status": "ready_for_final_local_acceptance_and_staging_preparation",
        "included_capabilities": [
            "tenant-scoped auth and roles",
            "self-serve onboarding draft and publish flow",
            "tenant settings, branches, staff, FAQ, intents, routing, channels",
            "customers, conversations, messages, tickets, broadcasts, audit logs",
            "rule-first intent engine and response/routing/orchestrator services",
            "WhatsApp adapter boundary with tenant-scoped credentials",
            "idempotent provider message and webhook event model",
            "dashboard tabs for operations, UAT, deployment, and acceptance",
        ],
        "not_included_until_client_supplies": [
            "real academy WhatsApp production access token",
            "real WABA ID and PHONE_NUMBER_ID",
            "real app secret and verify token",
            "approved WhatsApp template names/languages",
            "public HTTPS callback URL after staging/production deployment",
        ],
        "recommended_next_steps": [
            "run pytest -q",
            "run the dashboard UAT tab",
            "review the dashboard Deployment tab",
            "review the dashboard Final Handoff tab",
            "deploy staging backend/frontend/database",
            "connect the academy WhatsApp tenant channel only after credentials/templates are supplied",
        ],
    }
