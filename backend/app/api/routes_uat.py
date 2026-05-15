from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import settings
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import Tenant
from app.services.intent_rules import IntentRules
from app.services.routing_engine import RoutingEngine
from app.services.working_hours import is_inside_working_hours

router = APIRouter(prefix="/uat", tags=["uat"])
intent_rules = IntentRules()
routing_engine = RoutingEngine()
UAT_FIXTURE_ENVS = {"development", "test"}

ACADEMY_UAT_CASES = [
    {"id": "pricing-basic", "message": "السلام عليكم كم السعر؟", "expected_intent": "PRICING", "expected_action": "AUTO_REPLY", "note": "price + greeting should still select pricing"},
    {"id": "registration", "message": "ابغى اسجل في دورة انجليزي", "expected_intent": "REGISTRATION", "expected_action": "AUTO_REPLY", "note": "registration path from tenant FAQ"},
    {"id": "location", "message": "وين موقعكم في جدة؟", "expected_intent": "LOCATION", "expected_action": "AUTO_REPLY", "note": "location answer is tenant knowledge"},
    {"id": "payment-transfer", "message": "حولت المبلغ وابغى اتأكد من السداد", "expected_intent": "PAYMENT_TRANSFER", "expected_action": "TICKET", "note": "finance issue should become specialist ticket"},
    {"id": "certificate", "message": "متى استلم الشهادة؟", "expected_intent": "CERTIFICATES", "expected_action": "TICKET", "note": "certificate issue routes to certificates"},
    {"id": "complaint", "message": "عندي شكوى ومشكلة مع الدورة", "expected_intent": "COMPLAINT", "expected_action": "TICKET", "note": "complaints must be high priority human takeover"},
    {"id": "human-request", "message": "ابغى موظف يرد علي", "expected_intent": "HUMAN_REQUEST", "expected_action": "HANDOFF", "note": "explicit human request stops bot"},
    {"id": "women-section", "message": "هل يوجد قسم نسائي؟", "expected_intent": "WOMENS_SECTION", "expected_action": "AUTO_REPLY", "note": "women section is tenant-specific intent"},
    {"id": "kids-section", "message": "فيه قسم للاطفال؟", "expected_intent": "KIDS_SECTION", "expected_action": "AUTO_REPLY", "note": "kids section is tenant-specific intent"},
    {"id": "accreditation", "message": "المعهد معتمد؟", "expected_intent": "ACCREDITATION", "expected_action": "AUTO_REPLY", "note": "accreditation is tenant FAQ"},
]


class CustomUatRequest(BaseModel):
    message: str
    expected_intent: str | None = None
    expected_action: str | None = None


def require_uat_fixture_access(
    ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
    x_uat_fixture_access: str | None = Header(default=None, alias="X-UAT-Fixture-Access"),
) -> dict:
    if settings.app_env not in UAT_FIXTURE_ENVS:
        raise HTTPException(status_code=403, detail="UAT webhook fixtures are not available in this environment")
    user = ctx.get("user")
    explicit_test_permission = (x_uat_fixture_access or "").strip().lower() == "true"
    if not getattr(user, "is_platform_admin", False) and not explicit_test_permission:
        raise HTTPException(status_code=403, detail="UAT fixture access requires explicit test permission")
    return ctx


def evaluate_case(db: Session, tenant: Tenant, case: dict):
    intent = intent_rules.classify(db, tenant.id, case["message"])
    route = routing_engine.decide(db, tenant.id, intent.intent_code)
    expected_intent = case.get("expected_intent")
    expected_action = case.get("expected_action")
    passed = True
    if expected_intent:
        passed = passed and intent.intent_code == expected_intent
    if expected_action:
        passed = passed and route.action == expected_action
    return {
        **case,
        "actual_intent": intent.intent_code,
        "actual_action": route.action,
        "confidence": intent.confidence,
        "matched_phrases": intent.matched_phrases,
        "mixed": intent.mixed,
        "route": asdict(route),
        "passed": passed,
    }


@router.get("/academy-cases")
def academy_cases(
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    return {"cases": ACADEMY_UAT_CASES}


@router.post("/run-academy-cases")
def run_academy_cases(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    results = [evaluate_case(db, tenant, case) for case in ACADEMY_UAT_CASES]
    passed = sum(1 for r in results if r["passed"])
    return {
        "mode": "classification_only_no_messages_created",
        "inside_working_hours": is_inside_working_hours(db, tenant),
        "passed": passed,
        "total": len(results),
        "results": results,
    }


@router.post("/custom")
def custom_uat(
    payload: CustomUatRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    return evaluate_case(db, tenant, {"id": "custom", "message": payload.message, "expected_intent": payload.expected_intent, "expected_action": payload.expected_action, "note": "custom tenant UAT check"})

# Batch 6: WhatsApp webhook UAT fixtures.
# These endpoints let the business/admin validate realistic WhatsApp payloads without
# hitting Meta and without creating customer conversations/messages.
import hashlib
import hmac
import json
from app.models.entities import ChannelConfig
from app.services.tenant_channel_service import TenantChannelService
from app.services.whatsapp_adapter import WhatsAppAdapter

channel_service_for_uat = TenantChannelService()
whatsapp_adapter_for_uat = WhatsAppAdapter()


def _tenant_phone_number_id(db: Session, tenant_id: int) -> str:
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel_type == "whatsapp").first()
    if not channel:
        return "phone-number-id-not-configured"
    creds = channel_service_for_uat.credentials(channel)
    return str(channel.public_config_json.get("phone_number_id") or creds.get("phone_number_id") or "phone-number-id-not-configured")


def _tenant_app_secret(db: Session, tenant_id: int) -> str | None:
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel_type == "whatsapp").first()
    if not channel:
        return None
    return channel_service_for_uat.credentials(channel).get("app_secret")


def _fixture_payload(*, case_id: str, phone_number_id: str, from_phone: str, message: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "uat_waba",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "966500000000",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {"profile": {"name": "UAT Customer"}, "wa_id": from_phone}
                            ],
                            "messages": [
                                {
                                    "from": from_phone,
                                    "id": f"wamid.uat.{case_id}",
                                    "timestamp": "1710000000",
                                    "text": {"body": message},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _signed_fixture(payload: dict, app_secret: str | None) -> dict:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = None
    if app_secret and app_secret != "pending":
        signature = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return {
        "payload": payload,
        "raw_body": raw.decode("utf-8"),
        "x_hub_signature_256": signature,
    }


@router.get("/whatsapp-fixtures")
def whatsapp_fixtures(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_uat_fixture_access),
):
    phone_number_id = _tenant_phone_number_id(db, tenant.id)
    app_secret = _tenant_app_secret(db, tenant.id)
    cases = []
    for case in ACADEMY_UAT_CASES:
        payload = _fixture_payload(
            case_id=case["id"],
            phone_number_id=phone_number_id,
            from_phone="966500000001",
            message=case["message"],
        )
        cases.append({**case, **_signed_fixture(payload, app_secret)})
    return {
        "mode": "webhook_payload_fixtures_no_messages_created",
        "tenant": tenant.slug,
        "phone_number_id": phone_number_id,
        "signature_available": bool(app_secret and app_secret != "pending"),
        "cases": cases,
    }


@router.post("/whatsapp-fixtures/{case_id}/simulate")
def simulate_whatsapp_fixture(
    case_id: str,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_uat_fixture_access),
):
    case = next((item for item in ACADEMY_UAT_CASES if item["id"] == case_id), None)
    if not case:
        return {"ok": False, "detail": "Unknown fixture id"}
    payload = _fixture_payload(
        case_id=case["id"],
        phone_number_id=_tenant_phone_number_id(db, tenant.id),
        from_phone="966500000001",
        message=case["message"],
    )
    normalized = whatsapp_adapter_for_uat.normalize_inbound(payload)
    if not normalized:
        return {"ok": False, "detail": "Fixture failed normalization"}
    result = evaluate_case(db, tenant, case)
    return {
        "ok": True,
        "mode": "normalized_and_classified_no_messages_created",
        "normalized": {
            "provider_message_id": normalized.provider_message_id,
            "customer_phone": normalized.customer_phone,
            "phone_number_id": normalized.phone_number_id,
            "text": normalized.text,
        },
        "result": result,
    }
