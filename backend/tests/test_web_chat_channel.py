from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes_webhook import WebChatMessageRequest, receive_web_chat_message
from app.models.entities import ChannelConfig, Conversation, Customer, FaqItem, Message, Tenant


class FakeRequest:
    def __init__(self, *, host: str = "127.0.0.1"):
        self.client = SimpleNamespace(host=host)


def enable_web_chat(db, tenant):
    row = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "web_chat")
        .first()
    )
    if not row:
        row = ChannelConfig(tenant_id=tenant.id, channel_type="web_chat")
        db.add(row)
    row.status = "configured"
    row.public_config_json = {"enabled": True}
    db.commit()
    return row


def test_web_chat_message_creates_customer_conversation_and_returns_reply(db, tenant):
    enable_web_chat(db, tenant)

    result = receive_web_chat_message(
        tenant.slug,
        WebChatMessageRequest(visitor_id=None, message="what is the price?", display_name="Visitor One"),
        FakeRequest(),
        db=db,
    )

    assert result["visitor_id"].startswith("wc_")
    assert result["reply"] == "The course costs 1500 SAR and lasts one month."
    assert result["state"] == "BOT_ACTIVE"
    assert result["handoff"] is False

    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.phone.startswith("webchat:")).one()
    assert customer.name == "Visitor One"
    assert "channel:web_chat" in customer.tags_json
    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.channel_type == "web_chat").one()
    assert str(conversation.id) == result["conversation_id"]
    assert db.query(Message).filter(Message.tenant_id == tenant.id, Message.conversation_id == conversation.id).count() == 2


def test_web_chat_reuses_existing_visitor_identity(db, tenant):
    enable_web_chat(db, tenant)

    first = receive_web_chat_message(
        tenant.slug,
        WebChatMessageRequest(visitor_id="visitor-123", message="hello", display_name=None),
        FakeRequest(),
        db=db,
    )
    second = receive_web_chat_message(
        tenant.slug,
        WebChatMessageRequest(visitor_id="visitor-123", message="what is the price?", display_name=None),
        FakeRequest(),
        db=db,
    )

    assert first["visitor_id"] == "visitor-123"
    assert second["visitor_id"] == "visitor-123"
    assert first["conversation_id"] == second["conversation_id"]
    assert db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.phone == f"webchat:{tenant.id}:visitor-123").count() == 1


def test_web_chat_unknown_tenant_returns_safe_error(db):
    with pytest.raises(HTTPException) as exc:
        receive_web_chat_message(
            "missing-tenant",
            WebChatMessageRequest(visitor_id=None, message="hello", display_name=None),
            FakeRequest(),
            db=db,
        )
    assert exc.value.status_code == 404


def test_web_chat_tenant_isolation_with_same_visitor_id(db, tenant):
    enable_web_chat(db, tenant)
    other = Tenant(slug="other-web-chat", display_name="Other", timezone="Asia/Riyadh", default_lang="en", status="active")
    db.add(other)
    db.flush()
    db.add(FaqItem(tenant_id=other.id, topic_key="pricing", arabic_answer="Other tenant answer.", english_answer="Other tenant answer.", status="active"))
    enable_web_chat(db, other)

    first = receive_web_chat_message(
        tenant.slug,
        WebChatMessageRequest(visitor_id="same-visitor", message="price", display_name=None),
        FakeRequest(host="10.0.0.1"),
        db=db,
    )
    second = receive_web_chat_message(
        other.slug,
        WebChatMessageRequest(visitor_id="same-visitor", message="price", display_name=None),
        FakeRequest(host="10.0.0.2"),
        db=db,
    )

    assert "1500" in first["reply"]
    assert second["reply"] is None or "1500" not in second["reply"]
    assert db.query(Customer).filter(Customer.phone.like("webchat:%:same-visitor")).count() == 2


def test_web_chat_human_handoff_acknowledges_once_then_stays_silent(db, tenant):
    enable_web_chat(db, tenant)

    result = receive_web_chat_message(
        tenant.slug,
        WebChatMessageRequest(visitor_id="handoff-visitor", message="human", display_name=None),
        FakeRequest(),
        db=db,
    )

    assert result["reply"] == "I've passed your request to our team. A team member will reply as soon as possible."
    assert result["handoff"] is True
    assert result["state"] == "HUMAN_HANDOFF"

    followup = receive_web_chat_message(
        tenant.slug,
        WebChatMessageRequest(visitor_id="handoff-visitor", message="are you there?", display_name=None),
        FakeRequest(),
        db=db,
    )

    assert followup["reply"] is None
    assert followup["handoff"] is True
    assert followup["state"] == "HUMAN_HANDOFF"
