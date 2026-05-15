from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Branch,
    BusinessSetting,
    ChannelConfig,
    FaqItem,
    IntentDefinition,
    IntentKeyword,
    RoutingRule,
    Tenant,
)
from app.services.tenant_channel_service import TenantChannelService


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def tenant(db):
    t = Tenant(slug="test-tenant", display_name="Test Tenant", timezone="Asia/Riyadh", default_lang="ar", status="active")
    db.add(t)
    db.flush()
    db.add(Branch(
        tenant_id=t.id,
        name="Main",
        city="Jeddah",
        hours_json={"periods": [{"from": "00:00", "to": "23:59"}]},
        is_active=True,
    ))
    db.add(BusinessSetting(tenant_id=t.id, key="out_of_hours_policy", value_json={"mode": "auto_reply_only", "force_open": True}))
    intents = [
        ("GREETING", "Greeting", "greeting"),
        ("PRICING", "Pricing", "pricing"),
        ("COMPLAINT", "Complaint", "complaint"),
        ("HUMAN_REQUEST", "Human", "human_request"),
    ]
    for code, label, topic in intents:
        db.add(IntentDefinition(tenant_id=t.id, code=code, label=label, enabled=True, is_universal=False, default_response_topic_key=topic))
    db.add_all([
        IntentKeyword(tenant_id=t.id, intent_code="GREETING", phrase="السلام", weight=2, lang="ar"),
        IntentKeyword(tenant_id=t.id, intent_code="GREETING", phrase="hello", weight=2, lang="en"),
        IntentKeyword(tenant_id=t.id, intent_code="PRICING", phrase="السعر", weight=3, lang="ar"),
        IntentKeyword(tenant_id=t.id, intent_code="PRICING", phrase="بكم", weight=3, lang="ar"),
        IntentKeyword(tenant_id=t.id, intent_code="PRICING", phrase="price", weight=3, lang="en"),
        IntentKeyword(tenant_id=t.id, intent_code="PRICING", phrase="pricing", weight=3, lang="en"),
        IntentKeyword(tenant_id=t.id, intent_code="COMPLAINT", phrase="شكوى", weight=5, lang="ar"),
        IntentKeyword(tenant_id=t.id, intent_code="COMPLAINT", phrase="complaint", weight=5, lang="en"),
        IntentKeyword(tenant_id=t.id, intent_code="HUMAN_REQUEST", phrase="موظف", weight=5, lang="ar"),
        IntentKeyword(tenant_id=t.id, intent_code="HUMAN_REQUEST", phrase="human", weight=5, lang="en"),
    ])
    db.add_all([
        FaqItem(tenant_id=t.id, topic_key="greeting", question_ar="", english_question="Hello", arabic_answer="أهلاً بك، كيف نساعدك؟", english_answer="Welcome, how can we help you?", status="active"),
        FaqItem(tenant_id=t.id, topic_key="pricing", question_ar="", english_question="What is the price?", arabic_answer="سعر الدورة 1500 ريال ومدة الدورة شهر.", english_answer="The course costs 1500 SAR and lasts one month.", status="active"),
    ])
    db.add_all([
        RoutingRule(tenant_id=t.id, intent_code="GREETING", primary_owner_role="BOT", handoff_required=False, priority="normal"),
        RoutingRule(tenant_id=t.id, intent_code="PRICING", primary_owner_role="BOT", handoff_required=False, priority="normal"),
        RoutingRule(tenant_id=t.id, intent_code="COMPLAINT", primary_owner_role="OPERATIONS_STAFF", handoff_required=True, ticket_type="complaint", priority="high"),
        RoutingRule(tenant_id=t.id, intent_code="HUMAN_REQUEST", primary_owner_role="OPERATIONS_STAFF", handoff_required=True, ticket_type="handoff", priority="normal"),
    ])
    svc = TenantChannelService()
    channel = ChannelConfig(
        tenant_id=t.id,
        channel_type="whatsapp",
        status="connected",
        public_config_json={"phone_number_id": "phone-test", "live_send_enabled": False},
        encrypted_credentials=svc.encrypt_credentials({"verify_token": "verify-test", "app_secret": "secret-test", "phone_number_id": "phone-test", "access_token": "pending"}),
    )
    db.add(channel)
    db.commit()
    db.refresh(t)
    return t
