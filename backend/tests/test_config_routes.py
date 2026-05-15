from types import SimpleNamespace

from app.api.routes_config import (
    FaqCreate,
    FaqUpdate,
    IntentCreate,
    IntentUpdate,
    RoutingRuleUpsert,
    StaffCreate,
    archive_faq,
    create_staff,
    create_faq,
    create_intent,
    delete_faq_permanently,
    delete_intent,
    delete_knowledge_item,
    list_faq,
    list_staff,
    list_intents,
    list_routing_rules,
    upsert_routing_rule,
    update_faq,
    update_intent,
)
from app.api.routes_auth import login
from app.core.security import verify_password
from app.core.tenancy import ROLE_BUSINESS_ADMIN, ROLE_OPERATIONS_STAFF, require_tenant_roles
from app.models.entities import AuditLog, FaqItem, IntentDefinition, IntentKeyword, RoutingRule, TenantUserRole, TrainingExample, User
from app.schemas.auth import LoginRequest
from app.services.response_engine import ResponseEngine
from pydantic import ValidationError
import pytest


class FakeRequest:
    client = SimpleNamespace(host="127.0.0.1")


def test_faq_routes_support_english_question_and_archive(db, tenant):
    result = create_faq(
        payload=FaqCreate(
            topic_key="location",
            question_ar="وين موقعكم؟",
            english_question="Where are you located?",
            arabic_answer="نحن في جدة.",
            english_answer="We are in Jeddah.",
            status="active",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=11)},
    )

    update_faq(
        faq_id=result["id"],
        payload=FaqUpdate(english_question="Where is your branch located?"),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=11)},
    )
    archive_faq(
        faq_id=result["id"],
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=11)},
    )

    rows = list_faq(tenant=tenant, db=db, _={})
    created = next(row for row in rows if row["id"] == result["id"])
    assert created["english_question"] == "Where is your branch located?"
    assert created["status"] == "archived"


def test_delete_faq_permanently_removes_row(db, tenant):
    result = create_faq(
        payload=FaqCreate(
            topic_key="temp_delete",
            arabic_answer="سيتم الحذف",
            english_answer="Will be deleted",
            status="active",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=12)},
    )

    deleted = delete_faq_permanently(
        faq_id=result["id"],
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=12)},
    )

    assert deleted["status"] == "deleted"
    assert db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.id == result["id"]).count() == 0


def test_intent_routes_support_custom_response_and_delete(db, tenant):
    create_result = create_intent(
        payload=IntentCreate(
            code="DELIVERY_INFO",
            label="Delivery info",
            enabled=True,
            supported_languages="both",
            response_mode="custom",
            custom_response_ar="التوصيل متاح داخل جدة.",
            custom_response_en="Delivery is available inside Jeddah.",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=22)},
    )

    intent_row = next(row for row in list_intents(tenant=tenant, db=db, _={}) if row["id"] == create_result["id"])
    assert intent_row["response_mode"] == "custom"
    assert intent_row["supported_languages"] == "both"

    update_intent(
        intent_id=create_result["id"],
        payload=IntentUpdate(custom_response_en="Delivery is available across Jeddah."),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=22)},
    )

    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="DELIVERY_INFO", phrase="do you deliver", weight=2, lang="en"))
    db.add(TrainingExample(tenant_id=tenant.id, raw_text="do you deliver", normalized_text="do you deliver", labeled_intent="DELIVERY_INFO", source="manual"))
    db.commit()

    delete_intent(
        intent_id=create_result["id"],
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=22)},
    )

    assert db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.intent_code == "DELIVERY_INFO").count() == 0
    assert db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == "DELIVERY_INFO").count() == 0
    assert db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id, TrainingExample.labeled_intent == "DELIVERY_INFO").count() == 0


def test_intent_routes_support_business_settings_response_mode(db, tenant):
    create_result = create_intent(
        payload=IntentCreate(
            code="CONTACT",
            label="Contact",
            enabled=True,
            supported_languages="both",
            response_mode="business_settings",
            default_response_topic_key="contact",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=23)},
    )

    intent_row = next(row for row in list_intents(tenant=tenant, db=db, _={}) if row["id"] == create_result["id"])
    assert intent_row["response_mode"] == "business_settings"
    assert intent_row["default_response_topic_key"] == "contact"


def test_response_engine_prefers_custom_intent_response(db, tenant):
    result = create_intent(
        payload=IntentCreate(
            code="DELIVERY_STATUS",
            label="Delivery status",
            enabled=True,
            supported_languages="both",
            response_mode="custom",
            custom_response_ar="التوصيل متاح.",
            custom_response_en="Delivery is available.",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=33)},
    )

    row = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.topic_key == "pricing").first()
    assert row is not None
    response = ResponseEngine().build_response(db, tenant, "DELIVERY_STATUS")
    assert response == "التوصيل متاح."
    assert result["status"] == "created"


def test_response_engine_prefers_localized_faq_when_duplicate_topic_rows_exist(db, tenant):
    db.add(
        FaqItem(
            tenant_id=tenant.id,
            topic_key="how_are_you",
            question_ar="كيف حالك؟",
            arabic_answer="انا بخير",
            english_answer=None,
            status="active",
        )
    )
    db.add(
        FaqItem(
            tenant_id=tenant.id,
            topic_key="how_are_you",
            english_question="How are you?",
            arabic_answer="انا بخير",
            english_answer="I am fine",
            status="active",
        )
    )
    db.add(
        IntentDefinition(
            tenant_id=tenant.id,
            code="HOW_ARE_YOU",
            label="How are you",
            enabled=True,
            is_universal=False,
            default_response_topic_key="how_are_you",
        )
    )
    db.commit()

    response = ResponseEngine().build_response(db, tenant, "HOW_ARE_YOU", preferred_lang="en")
    assert response == "I am fine"


def test_delete_knowledge_item_removes_intent_and_all_matching_faq_rows(db, tenant):
    create_intent(
        payload=IntentCreate(
            code="MENU",
            label="Menu",
            enabled=True,
            supported_languages="both",
            response_mode="faq",
            default_response_topic_key="menu",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=34)},
    )
    create_faq(
        payload=FaqCreate(
            topic_key="menu",
            arabic_answer="القائمة العربية",
            english_answer=None,
            status="active",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=34)},
    )
    create_faq(
        payload=FaqCreate(
            topic_key="menu",
            arabic_answer="القائمة العربية",
            english_answer="English menu",
            status="active",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=34)},
    )

    result = delete_knowledge_item(
        intent_code="MENU",
        topic_key="menu",
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=34)},
    )

    assert result["status"] == "deleted"
    assert db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == "MENU").count() == 0
    assert db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.intent_code == "MENU").count() == 0
    assert db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == "MENU").count() == 0
    assert db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.topic_key == "menu").count() == 0


def test_routing_rule_supports_offer_handoff_configuration(db, tenant):
    result = upsert_routing_rule(
        intent_code="PRICING",
        payload=RoutingRuleUpsert(
            intent_code="PRICING",
            primary_owner_role="OPERATIONS_STAFF",
            notify_roles_json=["SUPERVISOR"],
            handoff_required=False,
            ticket_type="pricing_help",
            priority="normal",
            response_behavior="offer_handoff",
            followup_question_ar="هل تحتاج تفاصيل إضافية من موظف؟",
            followup_question_en="Need a human agent for more details?",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=44)},
    )

    assert result["status"] == "saved"
    rows = list_routing_rules(tenant=tenant, db=db, ctx={"user": SimpleNamespace(id=44)})
    pricing = next(row for row in rows if row["intent_code"] == "PRICING")
    assert pricing["response_behavior"] == "offer_handoff"
    assert pricing["followup_question_ar"] == "هل تحتاج تفاصيل إضافية من موظف؟"
    assert pricing["ticket_type"] == "pricing_help"


def test_staff_create_requires_explicit_password():
    with pytest.raises(ValidationError):
        StaffCreate(email="staff-missing@example.com", full_name="Staff Missing", roles=[ROLE_OPERATIONS_STAFF])


def test_staff_creation_hashes_password_and_does_not_leak_passwords(db, tenant):
    result = create_staff(
        payload=StaffCreate(
            email="staff-secure@example.com",
            full_name="Staff Secure",
            password="StaffPass123!",
            roles=[ROLE_OPERATIONS_STAFF],
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=55)},
    )

    user = db.query(User).filter(User.email == "staff-secure@example.com").one()
    staff_rows = list_staff(tenant=tenant, db=db, _={})
    created = next(row for row in staff_rows if row["id"] == user.id)
    audit = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id, AuditLog.action == "staff.created_or_updated").order_by(AuditLog.id.desc()).first()

    assert result == {"id": user.id, "status": "saved"}
    assert user.password_hash != "StaffPass123!"
    assert verify_password("StaffPass123!", user.password_hash)
    assert "password" not in result
    assert "password_hash" not in created
    assert "password" not in created
    assert audit is not None
    assert "password" not in (audit.details_json or {})


def test_created_staff_can_login_with_explicit_password(db, tenant):
    create_staff(
        payload=StaffCreate(
            email="staff-login@example.com",
            full_name="Staff Login",
            password="StaffLogin123!",
            roles=[ROLE_OPERATIONS_STAFF],
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=56)},
    )

    response = login(
        LoginRequest(email="staff-login@example.com", password="StaffLogin123!", tenant_slug=tenant.slug),
        request=FakeRequest(),
        db=db,
    )

    assert response.access_token
    assert response.user["email"] == "staff-login@example.com"


def test_non_admin_role_dependency_blocks_staff_creation(db, tenant):
    user = User(email="ops-only@example.com", full_name="Ops Only", password_hash="hash")
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code=ROLE_OPERATIONS_STAFF))
    db.commit()

    dependency = require_tenant_roles(ROLE_BUSINESS_ADMIN)

    with pytest.raises(Exception) as exc:
        dependency(db=db, user=user, tenant=tenant)

    assert getattr(exc.value, "status_code", None) == 403
