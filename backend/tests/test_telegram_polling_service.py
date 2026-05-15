from app.models.entities import ChannelConfig, Conversation, Customer, IntentDefinition, IntentKeyword, Message, RoutingRule, Ticket, WebhookEvent
from app.services.telegram_polling_service import TelegramPollingService
from app.services.tenant_channel_service import TenantChannelService


def test_poll_once_processes_telegram_updates(db, tenant, monkeypatch):
    svc = TenantChannelService()
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "telegram").first()
    if not channel:
        channel = ChannelConfig(
            tenant_id=tenant.id,
            channel_type="telegram",
            status="connected",
            public_config_json={"enabled": True, "live_send_enabled": False},
            encrypted_credentials=svc.encrypt_credentials({"bot_token": "123:abc"}),
        )
        db.add(channel)
        db.commit()
    else:
        channel.status = "connected"
        channel.public_config_json = {"enabled": True, "live_send_enabled": False}
        channel.encrypted_credentials = svc.encrypt_credentials({"bot_token": "123:abc"})
        db.commit()

    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.delete_webhook",
        lambda self, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.get_updates",
        lambda self, **kwargs: {
            "ok": True,
            "result": [
                {
                    "update_id": 5001,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 99887766, "type": "private"},
                        "text": "كم السعر؟",
                    },
                }
            ],
        },
    )

    results = TelegramPollingService().poll_once(db)
    db.commit()

    assert len(results) == 1
    assert results[0].updates_processed == 1
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "telegram").count() == 1


def test_telegram_polling_supports_offer_handoff_confirmation(db, tenant, monkeypatch):
    routing_rule = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == "PRICING").first()
    routing_rule.primary_owner_role = "OPERATIONS_STAFF"
    routing_rule.handoff_required = False
    routing_rule.ticket_type = "pricing_help"
    routing_rule.escalation_json = {
        "response_behavior": "offer_handoff",
        "followup_question_ar": "هل تحتاج تفاصيل إضافية من موظف؟",
    }
    db.commit()

    svc = TenantChannelService()
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "telegram").first()
    if not channel:
        channel = ChannelConfig(
            tenant_id=tenant.id,
            channel_type="telegram",
            status="connected",
            public_config_json={"enabled": True, "live_send_enabled": False},
            encrypted_credentials=svc.encrypt_credentials({"bot_token": "123:abc"}),
        )
        db.add(channel)
        db.commit()

    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.delete_webhook",
        lambda self, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.get_updates",
        lambda self, **kwargs: {
            "ok": True,
            "result": [
                {
                    "update_id": 7001,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 88776655, "type": "private"},
                        "text": "كم السعر؟",
                    },
                }
            ],
        },
    )

    TelegramPollingService().poll_once(db)
    db.commit()

    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.channel_type == "telegram").one()
    assert conversation.state == "WAITING_FOR_HANDOFF_CONFIRMATION"

    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.get_updates",
        lambda self, **kwargs: {
            "ok": True,
            "result": [
                {
                    "update_id": 7002,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 88776655, "type": "private"},
                        "text": "نعم",
                    },
                }
            ],
        },
    )

    TelegramPollingService().poll_once(db)
    db.commit()

    db.refresh(conversation)
    assert conversation.state == "HUMAN_HANDOFF"
    ticket = db.query(Ticket).filter(Ticket.tenant_id == tenant.id, Ticket.conversation_id == conversation.id).one()
    assert ticket.ticket_type == "pricing_help"


def test_telegram_polling_replies_in_english_when_customer_message_is_english(db, tenant, monkeypatch):
    svc = TenantChannelService()
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "telegram").first()
    if not channel:
        channel = ChannelConfig(
            tenant_id=tenant.id,
            channel_type="telegram",
            status="connected",
            public_config_json={"enabled": True, "live_send_enabled": False},
            encrypted_credentials=svc.encrypt_credentials({"bot_token": "123:abc"}),
        )
        db.add(channel)
        db.commit()

    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.delete_webhook",
        lambda self, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.get_updates",
        lambda self, **kwargs: {
            "ok": True,
            "result": [
                {
                    "update_id": 7101,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 77665544, "type": "private"},
                        "text": "what is the price?",
                    },
                }
            ],
        },
    )

    TelegramPollingService().poll_once(db)
    db.commit()

    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.channel_type == "telegram").order_by(Conversation.id.desc()).first()
    assert conversation is not None
    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.id == conversation.customer_id).one()
    assert customer.preferred_lang == "en"

    outbound = (
        db.query(Message)
        .filter(Message.tenant_id == tenant.id, Message.conversation_id == conversation.id, Message.direction == "outbound")
        .order_by(Message.id.desc())
        .first()
    )
    assert outbound is not None
    assert outbound.text == "The course costs 1500 SAR and lasts one month."


def test_telegram_polling_uses_live_location_settings_reply(db, tenant, monkeypatch):
    db.add(IntentDefinition(
        tenant_id=tenant.id,
        code="LOCATION",
        label="Location",
        enabled=True,
        is_universal=False,
        supported_languages="both",
        response_mode="business_settings",
        default_response_topic_key="location",
    ))
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="LOCATION", phrase="where are you located", weight=3, lang="en"))
    db.add(RoutingRule(tenant_id=tenant.id, intent_code="LOCATION", primary_owner_role="BOT", handoff_required=False, priority="normal"))
    db.commit()

    svc = TenantChannelService()
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "telegram").first()
    if not channel:
        channel = ChannelConfig(
            tenant_id=tenant.id,
            channel_type="telegram",
            status="connected",
            public_config_json={"enabled": True, "live_send_enabled": False},
            encrypted_credentials=svc.encrypt_credentials({"bot_token": "123:abc"}),
        )
        db.add(channel)
        db.commit()

    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.delete_webhook",
        lambda self, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        "app.services.telegram_polling_service.TelegramAdapter.get_updates",
        lambda self, **kwargs: {
            "ok": True,
            "result": [
                {
                    "update_id": 7201,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 66778811, "type": "private"},
                        "text": "where are you located?",
                    },
                }
            ],
        },
    )

    TelegramPollingService().poll_once(db)
    db.commit()

    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.channel_type == "telegram").order_by(Conversation.id.desc()).first()
    outbound = (
        db.query(Message)
        .filter(Message.tenant_id == tenant.id, Message.conversation_id == conversation.id, Message.direction == "outbound")
        .order_by(Message.id.desc())
        .first()
    )
    assert outbound is not None
    assert "Our location:" in outbound.text
