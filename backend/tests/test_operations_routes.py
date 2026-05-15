from types import SimpleNamespace

from app.api.routes_operations import ConversationReplyRequest, reply_to_conversation
from app.models.entities import AuditLog, ChannelConfig, Conversation, Customer, Message


def test_reply_to_conversation_stores_manual_outbound_message(db, tenant):
    customer = Customer(tenant_id=tenant.id, phone="0500000099", preferred_lang="ar")
    db.add(customer)
    db.flush()
    conversation = Conversation(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_type="whatsapp",
        state="HUMAN_HANDOFF",
        owner_type="role",
        owner_ref="OPERATIONS_STAFF",
        last_intent="COMPLAINT",
    )
    db.add(conversation)
    db.commit()

    result = reply_to_conversation(
        conversation_id=conversation.id,
        payload=ConversationReplyRequest(text="سيتم التواصل معك خلال دقائق"),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=77)},
    )

    assert result["status"] == "sent"
    row = db.query(Message).filter(Message.tenant_id == tenant.id, Message.id == result["message_id"]).one()
    assert row.conversation_id == conversation.id
    assert row.direction == "outbound"
    assert row.text == "سيتم التواصل معك خلال دقائق"
    assert row.intent_code == "MANUAL_REPLY"
    audit = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id, AuditLog.action == "conversation.reply_sent").one()
    assert audit.entity_id == str(conversation.id)


def test_reply_to_conversation_uses_telegram_delivery_identity(db, tenant):
    db.add(
        ChannelConfig(
            tenant_id=tenant.id,
            channel_type="telegram",
            status="connected",
            public_config_json={"enabled": True, "live_send_enabled": False},
            encrypted_credentials="placeholder",
        )
    )
    customer = Customer(
        tenant_id=tenant.id,
        phone="tg:99887766",
        preferred_lang="ar",
        tags_json=["channel:telegram", "telegram_chat_id:99887766", "telegram_reachable:true"],
    )
    db.add(customer)
    db.flush()
    conversation = Conversation(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_type="telegram",
        state="HUMAN_HANDOFF",
        owner_type="role",
        owner_ref="OPERATIONS_STAFF",
        last_intent="COMPLAINT",
    )
    db.add(conversation)
    db.commit()

    result = reply_to_conversation(
        conversation_id=conversation.id,
        payload=ConversationReplyRequest(text="تم استلام الشكوى"),
        tenant=tenant,
        db=db,
        ctx={"user": SimpleNamespace(id=88)},
    )

    row = db.query(Message).filter(Message.tenant_id == tenant.id, Message.id == result["message_id"]).one()
    assert row.payload_json["channel_type"] == "telegram"
    assert row.payload_json["provider"] == "telegram"
    assert "destination" not in row.payload_json
