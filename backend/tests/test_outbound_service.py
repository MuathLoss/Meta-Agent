from app.api.routes_dashboard import detail
from app.models.entities import ChannelConfig, Conversation, Customer
from app.services.outbound_service import OutboundService
from app.services.tenant_channel_service import TenantChannelService


def add_conversation(db, tenant, *, channel_type: str = "whatsapp") -> Conversation:
    customer = Customer(tenant_id=tenant.id, phone="0500000001", preferred_lang="ar")
    db.add(customer)
    db.flush()
    conversation = Conversation(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_type=channel_type,
        state="BOT_ACTIVE",
    )
    db.add(conversation)
    db.flush()
    return conversation


def configure_whatsapp_for_live_send(db, tenant) -> ChannelConfig:
    credential_service = TenantChannelService()
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "whatsapp").one()
    channel.status = "connected"
    channel.public_config_json = {"enabled": True, "live_send_enabled": True, "phone_number_id": "phone-test"}
    channel.encrypted_credentials = credential_service.encrypt_credentials({
        "access_token": "whatsapp-access-token-secret",
        "phone_number_id": "phone-test",
        "app_secret": "app-secret",
    })
    db.flush()
    return channel


def test_successful_outbound_storage_does_not_include_raw_provider_response(db, tenant, monkeypatch):
    configure_whatsapp_for_live_send(db, tenant)
    conversation = add_conversation(db, tenant)
    service = OutboundService()

    def fake_send_text(**kwargs):
        return {
            "messages": [{"id": "wamid.safe"}],
            "access_token": "leaked-token",
            "phone_number_id": "leaked-phone-id",
            "debug": {"authorization": "Bearer leaked"},
        }

    monkeypatch.setattr(service.whatsapp, "send_text", fake_send_text)

    message = service.send_or_store(
        db,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        channel_type="whatsapp",
        destination="0500000001",
        text="hello",
        intent_code="GREETING",
    )

    assert message.provider_message_id == "wamid.safe"
    assert message.payload_json == {
        "send_status": "sent",
        "provider": "whatsapp",
        "channel_type": "whatsapp",
        "provider_message_id": "wamid.safe",
    }
    assert "provider_response" not in message.payload_json
    assert "destination" not in message.payload_json
    assert "leaked-token" not in str(message.payload_json)


def test_outbound_failure_storage_does_not_include_raw_exception_text(db, tenant, monkeypatch):
    configure_whatsapp_for_live_send(db, tenant)
    conversation = add_conversation(db, tenant)
    service = OutboundService()

    def fake_send_text(**kwargs):
        raise RuntimeError("POST https://graph.test/messages?access_token=secret-token failed with Authorization: Bearer abc")

    monkeypatch.setattr(service.whatsapp, "send_text", fake_send_text)

    message = service.send_or_store(
        db,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        channel_type="whatsapp",
        destination="0500000001",
        text="hello",
        intent_code="GREETING",
    )

    assert message.payload_json == {
        "send_status": "send_failed",
        "provider": "whatsapp",
        "channel_type": "whatsapp",
        "error_type": "provider_send_error",
    }
    assert "error" not in message.payload_json
    assert "secret-token" not in str(message.payload_json)
    assert "Authorization" not in str(message.payload_json)


def test_telegram_unreachable_failure_uses_safe_error_category():
    service = OutboundService()

    payload = service.failure_payload(
        channel_type="telegram",
        exc=RuntimeError("403 Forbidden: bot was blocked by the user at https://api.telegram.org/bot123:secret/sendMessage"),
    )

    assert payload["error_type"] == "recipient_unreachable"
    assert service.is_unreachable_recipient_failure(channel_type="telegram", payload_json=payload)
    assert "bot123:secret" not in str(payload)


def test_dashboard_conversation_detail_still_returns_messages(db, tenant, monkeypatch):
    configure_whatsapp_for_live_send(db, tenant)
    conversation = add_conversation(db, tenant)
    service = OutboundService()
    monkeypatch.setattr(service.whatsapp, "send_text", lambda **kwargs: {"messages": [{"id": "wamid.detail"}]})
    service.send_or_store(
        db,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        channel_type="whatsapp",
        destination="0500000001",
        text="hello detail",
        intent_code="GREETING",
    )
    db.commit()

    response = detail(conversation_id=conversation.id, db=db, tenant=tenant, _={})

    assert response["messages"][0]["text"] == "hello detail"
    assert "payload_json" not in response["messages"][0]
