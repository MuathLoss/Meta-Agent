import asyncio
from types import SimpleNamespace

from app.api import routes_config
from app.api.routes_config import (
    FaqCreate,
    FaqUpdate,
    IntentCreate,
    IntentUpdate,
    RoutingRuleUpsert,
    StaffCreate,
    StaffRoleUpdate,
    TenantProfileUpdate,
    archive_faq,
    create_staff,
    replace_staff_roles,
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
    update_profile,
    update_intent,
    upload_profile_logo,
)
from app.api.routes_auth import login
from app.core.security import verify_password
from app.core.tenancy import ROLE_BUSINESS_ADMIN, ROLE_OPERATIONS_STAFF, require_tenant_roles
from app.models.entities import AuditLog, FaqItem, IntentDefinition, IntentKeyword, RoutingRule, Tenant, TenantUserRole, TrainingExample, User
from app.schemas.auth import LoginRequest
from app.services.response_engine import ResponseEngine
from fastapi import HTTPException
from pydantic import ValidationError
import pytest


class FakeRequest:
    client = SimpleNamespace(host="127.0.0.1")


class FakeUploadFile:
    def __init__(self, filename: str, content_type: str, content: bytes):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


def run_logo_upload(db, tenant, filename: str, content_type: str, content: bytes):
    return asyncio.run(
        upload_profile_logo(
            file=FakeUploadFile(filename, content_type, content),
            tenant=tenant,
            db=db,
            ctx={"user": SimpleNamespace(id=88)},
        )
    )


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


def make_other_workspace_admin(db):
    other = Tenant(slug="other-workspace", display_name="Other Workspace", timezone="Asia/Riyadh", default_lang="ar", status="active")
    owner = User(email="owner@other-workspace.example.com", full_name="Original Owner", password_hash="hash")
    db.add_all([other, owner])
    db.flush()
    db.add(TenantUserRole(tenant_id=other.id, user_id=owner.id, role_code=ROLE_BUSINESS_ADMIN))
    db.commit()
    return other, owner


def test_staff_create_refuses_account_that_belongs_to_another_workspace(db, tenant):
    other, owner = make_other_workspace_admin(db)

    with pytest.raises(HTTPException) as exc:
        create_staff(
            payload=StaffCreate(email=owner.email, full_name="Renamed By Stranger", password="Irrelevant123!", roles=[ROLE_OPERATIONS_STAFF]),
            tenant=tenant,
            db=db,
            ctx={"user": SimpleNamespace(id=60)},
        )

    db.rollback()
    db.refresh(owner)
    assert exc.value.status_code == 409
    assert owner.full_name == "Original Owner"
    assert db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == owner.id).count() == 0
    assert db.query(TenantUserRole).filter(TenantUserRole.tenant_id == other.id, TenantUserRole.user_id == owner.id).count() == 1


def test_staff_create_refuses_platform_admin_account(db, tenant):
    platform_admin = User(email="platform@example.com", full_name="Platform Admin", password_hash="hash", is_platform_admin=True)
    db.add(platform_admin)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        create_staff(
            payload=StaffCreate(email="platform@example.com", full_name="Taken Over", password="Irrelevant123!", roles=[ROLE_BUSINESS_ADMIN]),
            tenant=tenant,
            db=db,
            ctx={"user": SimpleNamespace(id=61)},
        )

    assert exc.value.status_code == 409
    assert db.query(TenantUserRole).filter(TenantUserRole.user_id == platform_admin.id).count() == 0


def test_staff_create_still_updates_roles_and_name_of_own_member(db, tenant):
    create_staff(
        payload=StaffCreate(email="member@example.com", full_name="First Name", password="MemberPass123!", roles=[ROLE_OPERATIONS_STAFF]),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=62)},
    )
    create_staff(
        payload=StaffCreate(email="member@example.com", full_name="Updated Name", password="Ignored123!", roles=[ROLE_OPERATIONS_STAFF, ROLE_BUSINESS_ADMIN]),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=62)},
    )

    member = db.query(User).filter(User.email == "member@example.com").one()
    roles = {row.role_code for row in db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == member.id).all()}
    assert member.full_name == "Updated Name"
    assert verify_password("MemberPass123!", member.password_hash)
    assert roles == {ROLE_OPERATIONS_STAFF, ROLE_BUSINESS_ADMIN}


def test_staff_roles_update_refuses_users_outside_the_workspace(db, tenant):
    other, owner = make_other_workspace_admin(db)

    with pytest.raises(HTTPException) as exc:
        replace_staff_roles(
            user_id=owner.id,
            payload=StaffRoleUpdate(roles=[ROLE_OPERATIONS_STAFF]),
            tenant=tenant,
            db=db,
            ctx={"user": SimpleNamespace(id=63)},
        )

    assert exc.value.status_code == 404
    assert db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == owner.id).count() == 0


def test_staff_roles_update_refuses_unknown_roles(db, tenant):
    create_staff(
        payload=StaffCreate(email="roles@example.com", full_name="Roles Member", password="RolesPass123!", roles=[ROLE_OPERATIONS_STAFF]),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=64)},
    )
    member = db.query(User).filter(User.email == "roles@example.com").one()

    with pytest.raises(HTTPException) as exc:
        replace_staff_roles(
            user_id=member.id,
            payload=StaffRoleUpdate(roles=["MADE_UP_ROLE"]),
            tenant=tenant,
            db=db,
            ctx={"user": SimpleNamespace(id=64)},
        )

    assert exc.value.status_code == 400
    roles = [row.role_code for row in db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == member.id).all()]
    assert roles == [ROLE_OPERATIONS_STAFF]

    replace_staff_roles(
        user_id=member.id,
        payload=StaffRoleUpdate(roles=[ROLE_BUSINESS_ADMIN]),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=64)},
    )
    roles = [row.role_code for row in db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant.id, TenantUserRole.user_id == member.id).all()]
    assert roles == [ROLE_BUSINESS_ADMIN]


def test_custom_answer_topic_defaults_to_agent_reply_but_protected_topics_still_hand_off(db, tenant):
    create_intent(
        payload=IntentCreate(code="OPENING_OFFER", label="Opening offer", response_mode="custom", custom_response_en="We have an opening offer this month."),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=65)},
    )
    create_intent(
        payload=IntentCreate(code="PAYMENT_TRANSFER", label="Payment transfer", response_mode="custom", custom_response_en="Please send the transfer receipt."),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=65)},
    )

    offer = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == "OPENING_OFFER").one()
    payment = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == "PAYMENT_TRANSFER").one()
    assert offer.primary_owner_role == "BOT"
    assert offer.handoff_required is False
    assert offer.ticket_type is None
    assert payment.handoff_required is True
    assert payment.ticket_type == "payment"


def test_saving_custom_answer_corrects_untouched_default_handoff_only(db, tenant):
    untouched = IntentDefinition(tenant_id=tenant.id, code="REFUNDS", label="Refunds", enabled=True, response_mode="custom", custom_response_en="Refunds take five days.")
    chosen = IntentDefinition(tenant_id=tenant.id, code="WARRANTY", label="Warranty", enabled=True, response_mode="custom", custom_response_en="Warranty lasts one year.")
    db.add_all([untouched, chosen])
    db.flush()
    db.add_all([
        RoutingRule(tenant_id=tenant.id, intent_code="REFUNDS", primary_owner_role=ROLE_OPERATIONS_STAFF, handoff_required=True, ticket_type="handoff", priority="normal", escalation_json={"reason": "custom_intent_without_default_response"}),
        RoutingRule(tenant_id=tenant.id, intent_code="WARRANTY", primary_owner_role=ROLE_OPERATIONS_STAFF, handoff_required=True, ticket_type="handoff", priority="normal", escalation_json={"reason": "custom_intent_without_default_response", "response_behavior": "immediate_handoff"}),
    ])
    db.commit()

    for row in (untouched, chosen):
        update_intent(intent_id=row.id, payload=IntentUpdate(label=row.label), tenant=tenant, db=db, ctx={"user": SimpleNamespace(id=66)})

    refunds = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == "REFUNDS").one()
    warranty = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == "WARRANTY").one()
    assert refunds.primary_owner_role == "BOT"
    assert refunds.handoff_required is False
    assert warranty.primary_owner_role == ROLE_OPERATIONS_STAFF
    assert warranty.handoff_required is True
    assert db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id, AuditLog.action == "routing_rule.auto_corrected", AuditLog.entity_id == "REFUNDS").count() == 1


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


def test_logo_upload_rejects_svg_filename_even_with_png_content(db, tenant, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_config, "UPLOAD_ROOT", tmp_path)

    with pytest.raises(Exception) as exc:
        run_logo_upload(db, tenant, "logo.svg", "image/png", b"\x89PNG\r\n\x1a\nsafe")

    assert getattr(exc.value, "status_code", None) == 400


def test_logo_upload_rejects_svg_content_named_png(db, tenant, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_config, "UPLOAD_ROOT", tmp_path)
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"

    with pytest.raises(Exception) as exc:
        run_logo_upload(db, tenant, "logo.png", "image/png", svg)

    assert getattr(exc.value, "status_code", None) == 400


def test_logo_upload_rejects_svg_content_type(db, tenant, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_config, "UPLOAD_ROOT", tmp_path)

    with pytest.raises(Exception) as exc:
        run_logo_upload(db, tenant, "logo.png", "image/svg+xml", b"\x89PNG\r\n\x1a\nsafe")

    assert getattr(exc.value, "status_code", None) == 400


def test_logo_upload_accepts_png_jpeg_and_webp(db, tenant, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_config, "UPLOAD_ROOT", tmp_path)

    uploads = [
        ("logo.png", "image/png", b"\x89PNG\r\n\x1a\nsafe", ".png"),
        ("logo.jpg", "image/jpeg", b"\xff\xd8\xff\xe0safe", ".jpg"),
        ("logo.webp", "image/webp", b"RIFF\x10\x00\x00\x00WEBPVP8 safe", ".webp"),
    ]

    for filename, content_type, content, extension in uploads:
        response = run_logo_upload(db, tenant, filename, content_type, content)
        assert response["status"] == "uploaded"
        assert response["logo_url"].startswith("/uploads/tenant_logos/test-tenant/")
        assert response["logo_url"].endswith(extension)


def test_logo_upload_rejects_oversized_file(db, tenant, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_config, "UPLOAD_ROOT", tmp_path)
    oversized = b"\x89PNG\r\n\x1a\n" + (b"x" * routes_config.MAX_LOGO_BYTES)

    with pytest.raises(Exception) as exc:
        run_logo_upload(db, tenant, "logo.png", "image/png", oversized)

    assert getattr(exc.value, "status_code", None) == 400
    assert "5 MB" in getattr(exc.value, "detail", "")


def test_logo_upload_uses_generated_filename_and_does_not_audit_original_filename(db, tenant, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_config, "UPLOAD_ROOT", tmp_path)

    response = run_logo_upload(db, tenant, "../../evil.png", "image/png", b"\x89PNG\r\n\x1a\nsafe")
    audit = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id, AuditLog.action == "settings.profile.logo_uploaded").order_by(AuditLog.id.desc()).first()

    assert "../" not in response["logo_url"]
    assert "evil.png" not in response["logo_url"]
    assert audit is not None
    assert audit.details_json["stored_filename"].endswith(".png")
    assert "filename" not in audit.details_json


def test_profile_update_rejects_unsafe_logo_urls(db, tenant):
    unsafe_values = [
        "https://example.test/logo.png",
        "http://example.test/logo.png",
        "data:image/png;base64,AAAA",
        "javascript:alert(1)",
        "//example.test/logo.png",
        "/uploads/tenant_logos/test-tenant/logo.svg",
        "/uploads/tenant_logos/test-tenant/../evil.png",
        "/static/logo.png",
    ]

    for value in unsafe_values:
        with pytest.raises(Exception) as exc:
            update_profile(
                payload=TenantProfileUpdate(logo_url=value),
                tenant=tenant,
                db=db,
                ctx={"user": SimpleNamespace(id=89)},
            )
        assert getattr(exc.value, "status_code", None) == 400


def test_profile_update_accepts_empty_null_and_safe_local_logo_url(db, tenant):
    update_profile(
        payload=TenantProfileUpdate(logo_url="/uploads/tenant_logos/test-tenant/logo.png"),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=90)},
    )

    assert update_profile(
        payload=TenantProfileUpdate(logo_url=""),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=90)},
    ) == {"status": "updated"}
    assert update_profile(
        payload=TenantProfileUpdate(logo_url=None),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=90)},
    ) == {"status": "updated"}

    for value in [
        "/uploads/tenant_logos/test-tenant/logo.jpg",
        "/uploads/tenant_logos/test-tenant/logo.jpeg",
        "/uploads/tenant_logos/test-tenant/logo.webp",
    ]:
        assert update_profile(
            payload=TenantProfileUpdate(logo_url=value),
            tenant=tenant,
            db=db,
            ctx={"user": SimpleNamespace(id=90)},
        ) == {"status": "updated"}


def test_non_admin_role_dependency_blocks_logo_upload(db, tenant):
    user = User(email="ops-logo@example.com", full_name="Ops Logo", password_hash="hash")
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code=ROLE_OPERATIONS_STAFF))
    db.commit()

    dependency = require_tenant_roles(ROLE_BUSINESS_ADMIN)

    with pytest.raises(Exception) as exc:
        dependency(db=db, user=user, tenant=tenant)

    assert getattr(exc.value, "status_code", None) == 403
