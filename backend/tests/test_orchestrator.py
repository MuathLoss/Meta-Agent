from datetime import datetime, timedelta, timezone

from app.api.routes_dashboard import inbox
from app.models.entities import Conversation, Customer, FaqItem, Message, RoutingRule, TenantBrand, Ticket
from app.services.ollama_intelligence_service import OllamaDecision
from app.services.orchestrator import ConversationOrchestrator


def ensure_dynamic_intent(db, tenant, *, code: str, topic_key: str | None = None):
    from app.models.entities import IntentDefinition, IntentKeyword, RoutingRule

    intent = IntentDefinition(
        tenant_id=tenant.id,
        code=code,
        label=code.replace("_", " ").title(),
        enabled=True,
        is_universal=False,
        supported_languages="both",
        response_mode="business_settings",
        default_response_topic_key=topic_key,
    )
    db.add(intent)
    db.flush()
    db.add(RoutingRule(tenant_id=tenant.id, intent_code=code, primary_owner_role="BOT", handoff_required=False, priority="normal"))
    return intent


def test_orchestrator_answers_and_stores_messages(db, tenant):
    decision = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000000",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="msg-1",
        payload_json={"test": True},
    )
    assert decision["status"] == "answered"
    assert "1500" in decision["auto_reply"]
    assert db.query(Message).filter(Message.tenant_id == tenant.id).count() == 2


def test_orchestrator_replies_in_english_for_english_customer_message(db, tenant):
    decision = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000009",
        text="what is the price?",
        channel_type="whatsapp",
        provider_message_id="msg-en-1",
    )
    assert decision["status"] == "answered"
    assert decision["auto_reply"] == "The course costs 1500 SAR and lasts one month."

    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.phone == "0500000009").one()
    assert customer.preferred_lang == "en"
    inbound = db.query(Message).filter(Message.tenant_id == tenant.id, Message.provider_message_id == "msg-en-1").one()
    assert inbound.payload_json["language"]["resolved_lang"] == "en"


def test_orchestrator_falls_back_to_tenant_default_when_selected_language_answer_is_missing(db, tenant):
    pricing = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.topic_key == "pricing").one()
    pricing.english_answer = None
    db.commit()

    decision = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000008",
        text="what is the price?",
        channel_type="whatsapp",
        provider_message_id="msg-en-fallback-1",
    )
    assert decision["status"] == "answered"
    assert decision["auto_reply"] == "سعر الدورة 1500 ريال ومدة الدورة شهر."


def test_customer_preferred_language_is_reused_for_unclear_followup(db, tenant):
    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000007",
        text="hello",
        channel_type="whatsapp",
        provider_message_id="msg-en-pref-1",
    )
    unclear = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000007",
        text="12345",
        channel_type="whatsapp",
        provider_message_id="msg-en-pref-2",
    )
    assert unclear["status"] == "clarify"
    assert unclear["auto_reply"] == "Could you clarify your request?"


def test_location_intent_uses_live_branch_settings(db, tenant):
    ensure_dynamic_intent(db, tenant, code="LOCATION", topic_key="location")
    from app.models.entities import IntentKeyword
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="LOCATION", phrase="وين موقعكم", weight=3, lang="ar"))
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="LOCATION", phrase="where are you located", weight=3, lang="en"))
    db.commit()

    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000040",
        text="وين موقعكم؟",
        channel_type="whatsapp",
        provider_message_id="location-1",
    )

    assert result["status"] == "answered"
    assert "موقعنا:" in result["auto_reply"]
    assert "Main" in result["auto_reply"]
    assert "Jeddah" in result["auto_reply"]


def test_location_answer_reflects_updated_branch_address(db, tenant):
    ensure_dynamic_intent(db, tenant, code="LOCATION", topic_key="location")
    from app.models.entities import Branch, IntentKeyword
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="LOCATION", phrase="where are you located", weight=3, lang="en"))
    branch = db.query(Branch).filter(Branch.tenant_id == tenant.id).first()
    branch.address = "Updated Address 123"
    db.commit()

    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000041",
        text="where are you located?",
        channel_type="whatsapp",
        provider_message_id="location-2",
    )

    assert result["status"] == "answered"
    assert "Our location:" in result["auto_reply"]
    assert "Updated Address 123" in result["auto_reply"]


def test_schedules_intent_uses_live_branch_hours(db, tenant):
    ensure_dynamic_intent(db, tenant, code="SCHEDULES", topic_key="schedules")
    from app.models.entities import Branch, IntentKeyword
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="SCHEDULES", phrase="متى تفتحون", weight=3, lang="ar"))
    branch = db.query(Branch).filter(Branch.tenant_id == tenant.id).first()
    branch.hours_json = {"periods": [{"from": "09:00", "to": "13:00"}, {"from": "16:30", "to": "21:30"}]}
    db.commit()

    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000042",
        text="متى تفتحون؟",
        channel_type="whatsapp",
        provider_message_id="hours-1",
    )

    assert result["status"] == "answered"
    assert "أوقات العمل لدينا:" in result["auto_reply"]
    assert "09:00 - 13:00" in result["auto_reply"]
    assert "16:30 - 21:30" in result["auto_reply"]


def test_contact_intent_uses_support_phone_from_profile(db, tenant):
    ensure_dynamic_intent(db, tenant, code="CONTACT", topic_key="contact")
    from app.models.entities import IntentKeyword
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="CONTACT", phrase="contact number", weight=3, lang="en"))
    brand = TenantBrand(tenant_id=tenant.id, support_phone="0555123456")
    db.add(brand)
    db.commit()

    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000043",
        text="contact number",
        channel_type="whatsapp",
        provider_message_id="contact-1",
    )

    assert result["status"] == "answered"
    assert result["auto_reply"] == "You can contact us on: 0555123456"


def test_dynamic_response_falls_back_to_faq_when_settings_data_is_missing(db, tenant):
    ensure_dynamic_intent(db, tenant, code="CONTACT", topic_key="contact")
    from app.models.entities import IntentKeyword
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="CONTACT", phrase="contact number", weight=3, lang="en"))
    db.add(FaqItem(tenant_id=tenant.id, topic_key="contact", arabic_answer="اتصلوا بنا", english_answer="Please contact our team.", status="active"))
    db.commit()

    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000044",
        text="contact number",
        channel_type="whatsapp",
        provider_message_id="contact-2",
    )

    assert result["status"] == "answered"
    assert result["auto_reply"] == "Please contact our team."


def test_location_question_can_use_dynamic_settings_without_manual_intent_setup(db, tenant):
    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000045",
        text="Where are you located?",
        channel_type="whatsapp",
        provider_message_id="dynamic-location-no-intent-1",
    )
    assert result["status"] == "answered"
    assert "Our location:" in result["auto_reply"]
    assert "Jeddah" in result["auto_reply"]


def test_arabic_location_question_can_use_dynamic_settings_without_manual_intent_setup(db, tenant):
    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000046",
        text="وين موقعكم",
        channel_type="whatsapp",
        provider_message_id="dynamic-location-no-intent-2",
    )
    assert result["status"] == "answered"
    assert "موقعنا:" in result["auto_reply"]


def test_orchestrator_deduplicates_provider_message_id(db, tenant):
    service = ConversationOrchestrator()
    first = service.handle_inbound(db, tenant=tenant, customer_phone="0500000001", text="كم السعر؟", channel_type="whatsapp", provider_message_id="dup-1")
    second = service.handle_inbound(db, tenant=tenant, customer_phone="0500000001", text="كم السعر؟", channel_type="whatsapp", provider_message_id="dup-1")
    assert first["status"] == "answered"
    assert second["status"] == "duplicate"
    assert db.query(Message).filter(Message.tenant_id == tenant.id, Message.provider_message_id == "dup-1").count() == 1


def test_complaint_creates_ticket_and_handoff(db, tenant):
    decision = ConversationOrchestrator().handle_inbound(db, tenant=tenant, customer_phone="0500000002", text="عندي شكوى", channel_type="whatsapp", provider_message_id="msg-complaint")
    assert decision["status"] == "handoff"
    assert db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.priority == "high").count() == 1
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).first()
    assert conv.state == "HUMAN_HANDOFF"


def test_telegram_inbound_customer_identity_is_stored_cleanly(db, tenant):
    decision = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="99887766",
        text="مرحبا",
        channel_type="telegram",
        provider_message_id="telegram-update-77",
        payload_json={"message": {"chat": {"id": 99887766, "username": "balu_guest"}}},
    )
    assert decision["status"] in {"answered", "clarify"}
    msg = db.query(Message).filter(Message.tenant_id == tenant.id, Message.provider_message_id == "telegram-update-77").first()
    conv = db.query(Conversation).filter(Conversation.id == msg.conversation_id).first()
    stored_customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.id == conv.customer_id).first()
    assert stored_customer.phone == "tg:99887766"
    assert "telegram_chat_id:99887766" in (stored_customer.tags_json or [])
    assert "telegram_reachable:true" in (stored_customer.tags_json or [])
    assert stored_customer.name == "@balu_guest"


def test_explicit_human_request_handoffs_immediately(db, tenant):
    decision = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000010",
        text="ابغى موظف",
        channel_type="whatsapp",
        provider_message_id="msg-human-1",
    )
    assert decision["status"] == "handoff"
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "HUMAN_HANDOFF"


def test_handoff_sends_one_acknowledgement_in_customer_language_then_stays_silent(db, tenant):
    service = ConversationOrchestrator()

    arabic = service.handle_inbound(db, tenant=tenant, customer_phone="0500000020", text="ابغى موظف", channel_type="whatsapp", provider_message_id="ack-ar-1")
    assert arabic["status"] == "handoff"
    assert arabic["auto_reply"] == "تم تحويل طلبك إلى فريقنا، وسيرد عليك أحد الموظفين في أقرب وقت ممكن."
    ack = db.query(Message).filter(Message.tenant_id == tenant.id, Message.id == arabic["outbound_message_id"]).one()
    assert ack.direction == "outbound"
    assert (ack.payload_json or {}).get("system_event") == "handoff_acknowledgement"

    waiting = service.handle_inbound(db, tenant=tenant, customer_phone="0500000020", text="الو", channel_type="whatsapp", provider_message_id="ack-ar-2")
    assert waiting["status"] == "stored"
    assert waiting["auto_reply"] is None
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.id == ack.conversation_id).one()
    assert db.query(Message).filter(Message.conversation_id == conv.id, Message.direction == "outbound").count() == 1

    english = service.handle_inbound(db, tenant=tenant, customer_phone="0500000021", text="I have a complaint about my order", channel_type="whatsapp", provider_message_id="ack-en-1")
    assert english["status"] == "handoff"
    assert english["auto_reply"] == "I've passed your request to our team. A team member will reply as soon as possible."


def test_request_for_a_person_hands_off_even_without_a_human_request_topic(db, tenant):
    from app.models.entities import IntentDefinition

    db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == "HUMAN_REQUEST").update({"enabled": False})
    db.commit()
    service = ConversationOrchestrator()

    english = service.handle_inbound(db, tenant=tenant, customer_phone="0500000030", text="I want to talk to a person", channel_type="whatsapp", provider_message_id="person-en")
    # The bot's own advice after declining a handoff must also work.
    suggested = service.handle_inbound(db, tenant=tenant, customer_phone="0500000031", text="I want a human agent", channel_type="whatsapp", provider_message_id="person-hint")
    arabic = service.handle_inbound(db, tenant=tenant, customer_phone="0500000032", text="أبي أكلم أحد لو سمحت", channel_type="whatsapp", provider_message_id="person-ar")

    for result in (english, suggested, arabic):
        assert result["status"] == "handoff"
        assert db.query(Ticket).filter(Ticket.id == result["ticket_id"]).one().ticket_type == "handoff"
    assert arabic["auto_reply"] == "تم تحويل طلبك إلى فريقنا، وسيرد عليك أحد الموظفين في أقرب وقت ممكن."


def test_ordinary_questions_are_not_mistaken_for_a_request_for_a_person():
    from app.services.intent_rules import asks_for_a_person

    assert asks_for_a_person("What are your customer service hours?") is False
    assert asks_for_a_person("Is the clinic open on Friday?") is False
    assert asks_for_a_person("هل عندكم موظفة؟") is False
    assert asks_for_a_person("I'd like to speak to someone about my bill") is True


def test_topic_with_custom_answer_is_answered_by_the_agent(db, tenant):
    from types import SimpleNamespace

    from app.api.routes_config import IntentCreate, create_intent
    from app.models.entities import IntentKeyword

    create_intent(
        payload=IntentCreate(
            code="APPOINTMENT",
            label="Book an appointment",
            supported_languages="both",
            response_mode="custom",
            custom_response_ar="تقدر تحجز موعدك من الرابط.",
            custom_response_en="You can book through the link.",
        ),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=77)},
    )
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="APPOINTMENT", phrase="appointment", weight=3, lang="en"))
    db.commit()

    decision = ConversationOrchestrator().handle_inbound(db, tenant=tenant, customer_phone="0500000022", text="I need an appointment", channel_type="whatsapp", provider_message_id="custom-answer-1")

    assert decision["status"] == "answered"
    assert decision["auto_reply"] == "You can book through the link."
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "BOT_ACTIVE"
    assert db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.conversation_id == conv.id).count() == 0


def test_pricing_can_offer_handoff_and_confirm_yes(db, tenant):
    routing_rule = db.query(RoutingRule).filter_by(tenant_id=tenant.id, intent_code="PRICING").first()
    routing_rule.primary_owner_role = "OPERATIONS_STAFF"
    routing_rule.handoff_required = False
    routing_rule.ticket_type = "pricing_help"
    routing_rule.escalation_json = {
        "response_behavior": "offer_handoff",
        "followup_question_ar": "هل تحتاج تفاصيل إضافية من موظف؟",
        "followup_question_en": "Do you want a human agent for more pricing details?",
    }
    db.commit()

    service = ConversationOrchestrator()
    first = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000030",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="offer-1",
    )
    assert first["status"] == "answered"
    assert "هل تحتاج تفاصيل إضافية من موظف؟" in first["auto_reply"]
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "WAITING_FOR_HANDOFF_CONFIRMATION"

    second = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000030",
        text="نعم",
        channel_type="whatsapp",
        provider_message_id="offer-2",
    )
    assert second["status"] == "handoff"
    db.refresh(conv)
    assert conv.state == "HUMAN_HANDOFF"
    ticket = db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.conversation_id == conv.id).one()
    assert ticket.ticket_type == "pricing_help"
    assert ticket.assigned_to == "OPERATIONS_STAFF"


def test_offer_handoff_followup_uses_customer_message_language(db, tenant):
    routing_rule = db.query(RoutingRule).filter_by(tenant_id=tenant.id, intent_code="PRICING").first()
    routing_rule.primary_owner_role = "OPERATIONS_STAFF"
    routing_rule.handoff_required = False
    routing_rule.ticket_type = "pricing_help"
    routing_rule.escalation_json = {
        "response_behavior": "offer_handoff",
        "followup_question_ar": "هل تحتاج تفاصيل إضافية من موظف؟",
        "followup_question_en": "Do you want a human agent for more pricing details?",
    }
    db.commit()

    decision = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000039",
        text="what is the price?",
        channel_type="whatsapp",
        provider_message_id="offer-en-1",
    )
    assert decision["status"] == "answered"
    assert "The course costs 1500 SAR and lasts one month." in decision["auto_reply"]
    assert "Do you want a human agent for more pricing details?" in decision["auto_reply"]


def test_pricing_can_offer_handoff_and_decline_no(db, tenant):
    routing_rule = db.query(RoutingRule).filter_by(tenant_id=tenant.id, intent_code="PRICING").first()
    routing_rule.primary_owner_role = "OPERATIONS_STAFF"
    routing_rule.handoff_required = False
    routing_rule.ticket_type = "pricing_help"
    routing_rule.escalation_json = {
        "response_behavior": "offer_handoff",
        "followup_question_ar": "هل تحتاج تفاصيل إضافية من موظف؟",
    }
    db.commit()

    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000031",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="offer-no-1",
    )
    declined = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000031",
        text="لا",
        channel_type="whatsapp",
        provider_message_id="offer-no-2",
    )
    assert declined["status"] == "answered"
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "BOT_ACTIVE"
    assert db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.conversation_id == conv.id).count() == 0


def test_unclear_reply_during_handoff_offer_asks_once_then_continues(db, tenant):
    routing_rule = db.query(RoutingRule).filter_by(tenant_id=tenant.id, intent_code="PRICING").first()
    routing_rule.primary_owner_role = "OPERATIONS_STAFF"
    routing_rule.handoff_required = False
    routing_rule.ticket_type = "pricing_help"
    routing_rule.escalation_json = {
        "response_behavior": "offer_handoff",
        "followup_question_ar": "هل تحتاج تفاصيل إضافية من موظف؟",
    }
    db.commit()

    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000032",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="offer-maybe-1",
    )
    unclear = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000032",
        text="يمكن",
        channel_type="whatsapp",
        provider_message_id="offer-maybe-2",
    )
    assert unclear["status"] == "clarify"
    assert "نعم" in unclear["auto_reply"]

    resumed = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000032",
        text="السلام عليكم",
        channel_type="whatsapp",
        provider_message_id="offer-maybe-3",
    )
    assert resumed["status"] == "answered"
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "BOT_ACTIVE"


def test_pending_handoff_confirmation_stays_tenant_scoped(db, tenant):
    routing_rule = db.query(RoutingRule).filter_by(tenant_id=tenant.id, intent_code="PRICING").first()
    routing_rule.primary_owner_role = "OPERATIONS_STAFF"
    routing_rule.handoff_required = False
    routing_rule.ticket_type = "pricing_help"
    routing_rule.escalation_json = {
        "response_behavior": "offer_handoff",
        "followup_question_ar": "هل تحتاج تفاصيل إضافية من موظف؟",
    }
    db.commit()

    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000033",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="tenant-scope-1",
    )
    result = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000034",
        text="نعم",
        channel_type="whatsapp",
        provider_message_id="tenant-scope-2",
    )
    assert result["status"] in {"clarify", "answered"}


def test_unknown_messages_clarify_before_handoff_then_threshold_handoffs(db, tenant):
    service = ConversationOrchestrator()
    first = service.handle_inbound(db, tenant=tenant, customer_phone="0500000011", text="asdfgh", channel_type="whatsapp", provider_message_id="junk-1")
    assert first["status"] == "clarify"
    for idx in range(2, 6):
        result = service.handle_inbound(db, tenant=tenant, customer_phone="0500000011", text=f"junk {idx}", channel_type="whatsapp", provider_message_id=f"junk-{idx}")
        assert result["status"] == "clarify"
    sixth = service.handle_inbound(db, tenant=tenant, customer_phone="0500000011", text="%%%%%%", channel_type="whatsapp", provider_message_id="junk-6")
    assert sixth["status"] == "handoff"
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "HUMAN_HANDOFF"


def test_spam_handoff_cooldown_returns_to_bot_after_one_minute(db, tenant, monkeypatch):
    service = ConversationOrchestrator()
    for idx, text in enumerate(["aaaa", "bbbb", "cccc", "dddd", "eeee", "ffff"], start=1):
        service.handle_inbound(db, tenant=tenant, customer_phone="0500000012", text=text, channel_type="whatsapp", provider_message_id=f"cooldown-{idx}")
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "HUMAN_HANDOFF"
    monkeypatch.setattr(service, "_now", lambda: datetime.now(timezone.utc) + timedelta(seconds=61))
    resumed = service.handle_inbound(db, tenant=tenant, customer_phone="0500000012", text="كم السعر", channel_type="whatsapp", provider_message_id="cooldown-7")
    assert resumed["status"] == "answered"
    db.refresh(conv)
    assert conv.state == "BOT_ACTIVE"


def test_customer_can_return_to_bot_from_handoff(db, tenant):
    service = ConversationOrchestrator()
    service.handle_inbound(db, tenant=tenant, customer_phone="0500000013", text="ابغى موظف", channel_type="whatsapp", provider_message_id="return-1")
    resumed = service.handle_inbound(db, tenant=tenant, customer_phone="0500000013", text="رجعني للبوت", channel_type="whatsapp", provider_message_id="return-2")
    assert resumed["status"] == "bot_active"
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "BOT_ACTIVE"


def test_human_handoff_auto_returns_to_bot_after_one_minute(db, tenant, monkeypatch):
    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000014",
        text="ابغى موظف",
        channel_type="whatsapp",
        provider_message_id="handoff-timeout-1",
    )
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    monkeypatch.setattr(service, "_now", lambda: datetime.now(timezone.utc) + timedelta(seconds=61))

    result = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000014",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="handoff-timeout-2",
    )

    assert result["status"] == "answered"
    db.refresh(conv)
    assert conv.state == "BOT_ACTIVE"
    assert conv.last_intent == "PRICING"


def test_staff_reply_keeps_the_bot_quiet_while_the_team_is_talking(db, tenant, monkeypatch):
    from types import SimpleNamespace

    from app.api.routes_operations import ConversationReplyRequest, reply_to_conversation

    service = ConversationOrchestrator()
    service.handle_inbound(db, tenant=tenant, customer_phone="0500000040", text="ابغى موظف", channel_type="whatsapp", provider_message_id="hold-1")
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()

    # Nobody answered within a minute, so the bot picked the conversation back up.
    monkeypatch.setattr(service, "_now", lambda: datetime.now(timezone.utc) + timedelta(minutes=2))
    assert service.handle_inbound(db, tenant=tenant, customer_phone="0500000040", text="كم السعر؟", channel_type="whatsapp", provider_message_id="hold-2")["status"] == "answered"

    # A team member replies: the conversation is theirs, and the customer's answer reaches them.
    reply_to_conversation(conv.id, ConversationReplyRequest(text="أهلاً، معك سارة من الفريق"), tenant=tenant, db=db, ctx={"user": SimpleNamespace(id=77)})
    db.refresh(conv)
    assert conv.state == "HUMAN_HANDOFF"
    monkeypatch.setattr(service, "_now", lambda: datetime.now(timezone.utc) + timedelta(minutes=5))
    quiet = service.handle_inbound(db, tenant=tenant, customer_phone="0500000040", text="كم السعر؟", channel_type="whatsapp", provider_message_id="hold-3")
    assert quiet["status"] == "stored"
    assert quiet["auto_reply"] is None

    # After 15 minutes without a team reply the bot helps again.
    monkeypatch.setattr(service, "_now", lambda: datetime.now(timezone.utc) + timedelta(minutes=16))
    assert service.handle_inbound(db, tenant=tenant, customer_phone="0500000040", text="كم السعر؟", channel_type="whatsapp", provider_message_id="hold-4")["status"] == "answered"


def test_complaint_handoff_auto_returns_to_bot_but_keeps_complaint_marker(db, tenant, monkeypatch):
    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000015",
        text="عندي شكوى",
        channel_type="whatsapp",
        provider_message_id="complaint-timeout-1",
    )
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "HUMAN_HANDOFF"
    assert conv.last_intent == "COMPLAINT"

    monkeypatch.setattr(service, "_now", lambda: datetime.now(timezone.utc) + timedelta(seconds=61))

    result = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000015",
        text="الو",
        channel_type="whatsapp",
        provider_message_id="complaint-timeout-2",
    )

    assert result["status"] in {"answered", "clarify"}
    db.refresh(conv)
    assert conv.state != "HUMAN_HANDOFF"
    assert (conv.metadata_json or {}).get("has_open_complaint") is True
    assert db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.conversation_id == conv.id, Ticket.status == "open").count() == 1


def test_complaint_typo_still_routes_to_handoff(db, tenant):
    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000016",
        text="عندي شكوا",
        channel_type="whatsapp",
        provider_message_id="complaint-typo-1",
    )

    assert result["status"] == "handoff"
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.last_intent == "COMPLAINT"


def test_random_nonsense_asks_for_clarification_instead_of_handoff(db, tenant):
    result = ConversationOrchestrator().handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000017",
        text="zzq 7781 blrp",
        channel_type="whatsapp",
        provider_message_id="nonsense-1",
    )

    assert result["status"] == "clarify"
    conv = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).order_by(Conversation.id.desc()).first()
    assert conv.state == "CLARIFYING"


def test_repeated_inbound_reuses_same_active_conversation(db, tenant):
    service = ConversationOrchestrator()
    first = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000020",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="reuse-1",
    )
    second = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000020",
        text="السلام عليكم",
        channel_type="whatsapp",
        provider_message_id="reuse-2",
    )
    assert first["status"] == "answered"
    assert second["status"] == "answered"
    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == tenant.id,
            Conversation.channel_type == "whatsapp",
        )
        .all()
    )
    assert len(conversations) == 1
    conversation = conversations[0]
    inbound_messages = (
        db.query(Message)
        .filter(
            Message.tenant_id == tenant.id,
            Message.conversation_id == conversation.id,
            Message.direction == "inbound",
        )
        .count()
    )
    assert inbound_messages == 2


def test_inbound_reopens_closed_conversation_instead_of_creating_new_one(db, tenant):
    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000021",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="reopen-1",
    )
    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).one()
    conversation.state = "CLOSED"
    db.commit()

    resumed = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000021",
        text="السلام عليكم",
        channel_type="whatsapp",
        provider_message_id="reopen-2",
    )

    assert resumed["status"] == "answered"
    conversations = db.query(Conversation).filter(Conversation.tenant_id == tenant.id).all()
    assert len(conversations) == 1
    db.refresh(conversation)
    assert conversation.state == "BOT_ACTIVE"


def test_inbox_collapses_duplicate_conversations_per_customer_and_channel(db, tenant):
    service = ConversationOrchestrator()
    service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000022",
        text="كم السعر؟",
        channel_type="whatsapp",
        provider_message_id="inbox-1",
    )
    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.phone == "0500000022").one()
    duplicate = Conversation(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_type="whatsapp",
        state="CLARIFYING",
        owner_type="BOT",
        owner_ref="BOT",
        last_intent="UNKNOWN",
    )
    db.add(duplicate)
    db.flush()
    db.add(
        Message(
            tenant_id=tenant.id,
            conversation_id=duplicate.id,
            direction="inbound",
            text="asdfgh",
            payload_json={"test": True},
        )
    )
    db.commit()

    rows = inbox(state=None, owner_ref=None, db=db, tenant=tenant, _={})

    matching = [row for row in rows if row["customer_id"] == customer.id and row["channel_type"] == "whatsapp"]
    assert len(matching) == 1
    assert matching[0]["id"] == duplicate.id


def test_exact_rule_match_does_not_call_ollama(db, tenant, monkeypatch):
    service = ConversationOrchestrator()
    monkeypatch.setattr("app.services.ollama_intelligence_service.settings.ollama_enabled", True)

    def fail_if_called(db, *, tenant, text):
        raise AssertionError("Ollama should not be called for strong rule matches")

    monkeypatch.setattr(service.ollama_intelligence, "classify", fail_if_called)

    result = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000030",
        text="بكم السعر؟",
        channel_type="whatsapp",
        provider_message_id="rule-no-ollama-1",
    )

    assert result["status"] == "answered"
    assert result["intent"]["source"] == "rules"


def test_fuzzy_message_uses_ollama_and_returns_tenant_faq(db, tenant, monkeypatch):
    service = ConversationOrchestrator()
    monkeypatch.setattr("app.services.ollama_intelligence_service.settings.ollama_enabled", True)
    tenant_id = tenant.id

    def fake_classify(db, *, tenant, text, language_hint=None):
        assert tenant.id == tenant_id
        assert text == "bkm el akl?"
        assert language_hint in {"ar", "en"}
        return OllamaDecision(
            intent_code="PRICING",
            confidence=0.84,
            faq_topic_key="pricing",
            needs_clarification=False,
            clarification_question=None,
            route_owner_role="BOT",
            reasoning_short="Pricing intent matched tenant FAQ.",
            raw_response={"message": {"content": "{}"}},
        )

    monkeypatch.setattr(service.ollama_intelligence, "classify", fake_classify)

    result = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000031",
        text="bkm el akl?",
        channel_type="whatsapp",
        provider_message_id="ollama-pricing-1",
    )

    assert result["status"] == "answered"
    assert result["intent"]["intent_code"] == "PRICING"
    assert result["intent"]["source"] == "ollama"
    assert "1500" in result["auto_reply"]


def test_ollama_timeout_falls_back_safely_without_crashing(db, tenant, monkeypatch):
    service = ConversationOrchestrator()
    monkeypatch.setattr("app.services.ollama_intelligence_service.settings.ollama_enabled", True)
    monkeypatch.setattr(service.ollama_intelligence, "classify", lambda db, *, tenant, text, language_hint=None: None)

    result = service.handle_inbound(
        db,
        tenant=tenant,
        customer_phone="0500000032",
        text="bkm el akl?",
        channel_type="whatsapp",
        provider_message_id="ollama-timeout-1",
    )

    assert result["status"] == "clarify"
    assert result["intent"]["intent_code"] == "UNKNOWN"
