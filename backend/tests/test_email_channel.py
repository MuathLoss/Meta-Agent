from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes_webhook import EmailInboundTestRequest, receive_email_inbound_test
from app.models.entities import ChannelConfig, Conversation, Customer, Message, Tenant
from app.services.customer_channel_identity_service import CustomerChannelIdentityService
from app.services.outbound_service import OutboundService
from app.services.tenant_channel_service import TenantChannelService


class FakeRequest:
    def __init__(self, *, host: str = "127.0.0.1", headers: dict | None = None):
        self.client = SimpleNamespace(host=host)
        self.headers = headers or {}


def enable_email(db, tenant, credentials: dict | None = None, *, live_send_enabled: bool = False):
    svc = TenantChannelService()
    row = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "email")
        .first()
    )
    if not row:
        row = ChannelConfig(tenant_id=tenant.id, channel_type="email")
        db.add(row)
    row.status = "configured"
    row.public_config_json = {"enabled": True, "live_send_enabled": live_send_enabled}
    if credentials is not None:
        row.encrypted_credentials = svc.encrypt_credentials(credentials)
    db.commit()
    return row


def smtp_credentials(**extra):
    return {
        "smtp_host": "smtp.example.test",
        "smtp_port": "587",
        "smtp_username": "tenant-smtp-user",
        "smtp_password": "tenant-smtp-password",
        "smtp_from_email": "support@example.test",
        "smtp_from_name": "Tenant Support",
        "use_tls": True,
        **extra,
    }


def test_email_channel_readiness_false_without_smtp_credentials(db, tenant):
    channel = enable_email(db, tenant, credentials={}, live_send_enabled=True)

    ready, reason = OutboundService().channel_ready(channel)

    assert ready is False
    assert reason == "missing_smtp_host"


def test_email_outbound_refuses_safely_when_customer_email_is_missing(db, tenant):
    enable_email(db, tenant, credentials=smtp_credentials(), live_send_enabled=True)
    customer = Customer(tenant_id=tenant.id, phone="0500000777", preferred_lang="en")
    db.add(customer)
    db.flush()
    conversation = Conversation(tenant_id=tenant.id, customer_id=customer.id, channel_type="email", state="BOT_ACTIVE")
    db.add(conversation)
    db.commit()

    destination = CustomerChannelIdentityService().delivery_address(customer, "email")
    message = OutboundService().send_or_store(
        db,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        channel_type="email",
        destination=destination,
        text="Hello from support",
        intent_code="MANUAL_REPLY",
    )

    assert message.payload_json["send_status"] == "send_failed"
    assert message.payload_json["reason"] == "missing_email_recipient"
    assert "smtp_password" not in str(message.payload_json)


def test_email_inbound_test_creates_customer_conversation_and_returns_reply(db, tenant):
    enable_email(db, tenant, credentials={}, live_send_enabled=False)

    result = receive_email_inbound_test(
        tenant.slug,
        EmailInboundTestRequest(from_email="Customer@Example.com", from_name="Customer One", subject="Pricing", text="what is the price?"),
        FakeRequest(),
        db=db,
    )

    assert result["reply"] == "The course costs 1500 SAR and lasts one month."
    assert result["state"] == "BOT_ACTIVE"
    assert result["handoff"] is False
    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.email == "customer@example.com").one()
    assert customer.phone == "email:customer@example.com"
    assert customer.name == "Customer One"
    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.channel_type == "email").one()
    assert str(conversation.id) == result["conversation_id"]
    inbound = db.query(Message).filter(Message.tenant_id == tenant.id, Message.conversation_id == conversation.id, Message.direction == "inbound").one()
    assert inbound.payload_json["source"] == "email_inbound_test"
    assert "subject" not in inbound.payload_json


def test_email_inbound_unknown_tenant_returns_safe_error(db):
    with pytest.raises(HTTPException) as exc:
        receive_email_inbound_test(
            "missing-tenant",
            EmailInboundTestRequest(from_email="customer@example.com", text="hello"),
            FakeRequest(),
            db=db,
        )
    assert exc.value.status_code == 404


def test_email_inbound_tenant_isolation_with_same_customer_email(db, tenant):
    enable_email(db, tenant, credentials={}, live_send_enabled=False)
    other = Tenant(slug="other-email", display_name="Other", timezone="Asia/Riyadh", default_lang="en", status="active")
    db.add(other)
    db.flush()
    enable_email(db, other, credentials={}, live_send_enabled=False)

    first = receive_email_inbound_test(
        tenant.slug,
        EmailInboundTestRequest(from_email="same@example.com", text="hello"),
        FakeRequest(host="10.0.0.1"),
        db=db,
    )
    second = receive_email_inbound_test(
        other.slug,
        EmailInboundTestRequest(from_email="same@example.com", text="hello"),
        FakeRequest(host="10.0.0.2"),
        db=db,
    )

    assert first["conversation_id"] != second["conversation_id"]
    assert db.query(Customer).filter(Customer.email == "same@example.com").count() == 2
    assert db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.email == "same@example.com").count() == 1
    assert db.query(Customer).filter(Customer.tenant_id == other.id, Customer.email == "same@example.com").count() == 1


def test_email_inbound_secret_requirement_when_configured(db, tenant):
    enable_email(db, tenant, credentials={"inbound_webhook_secret": "tenant-email-secret"}, live_send_enabled=False)
    payload = EmailInboundTestRequest(from_email="customer@example.com", text="hello")

    with pytest.raises(HTTPException) as exc:
        receive_email_inbound_test(tenant.slug, payload, FakeRequest(), db=db)
    assert exc.value.status_code == 403

    result = receive_email_inbound_test(
        tenant.slug,
        payload,
        FakeRequest(headers={"X-Channel-Webhook-Secret": "tenant-email-secret"}),
        db=db,
    )
    assert result["conversation_id"]
