from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes_webhook import (
    MetaSocialInboundTestRequest,
    receive_facebook_inbound_test,
    receive_instagram_inbound_test,
)
from app.models.entities import ChannelConfig, Conversation, Customer, Message, Tenant
from app.services.customer_channel_identity_service import CustomerChannelIdentityService
from app.services.outbound_service import OutboundService
from app.services.tenant_channel_service import TenantChannelService


class FakeRequest:
    def __init__(self, *, host: str = "127.0.0.1", headers: dict | None = None):
        self.client = SimpleNamespace(host=host)
        self.headers = headers or {}


def enable_social(
    db,
    tenant,
    channel_type: str,
    credentials: dict | None = None,
    *,
    enabled: bool = True,
    live_send_enabled: bool = False,
    status: str = "configured",
):
    svc = TenantChannelService()
    row = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == channel_type)
        .first()
    )
    if not row:
        row = ChannelConfig(tenant_id=tenant.id, channel_type=channel_type)
        db.add(row)
    row.status = status
    row.public_config_json = {"enabled": enabled, "live_send_enabled": live_send_enabled}
    if credentials is not None:
        row.encrypted_credentials = svc.encrypt_credentials(credentials)
    db.commit()
    return row


def meta_credentials(channel_type: str, **extra):
    base = {
        "page_access_token": "tenant-page-token",
        "app_secret": "tenant-app-secret",
        "verify_token": "tenant-verify-token",
        "graph_api_version": "v20.0",
    }
    if channel_type == "instagram":
        base["instagram_business_account_id"] = "ig-business-id"
    else:
        base["page_id"] = "facebook-page-id"
    return {**base, **extra}


def inbound(channel_type: str, tenant_slug: str, payload: MetaSocialInboundTestRequest, request: FakeRequest, db):
    if channel_type == "instagram":
        return receive_instagram_inbound_test(tenant_slug, payload, request, db=db)
    return receive_facebook_inbound_test(tenant_slug, payload, request, db=db)


@pytest.mark.parametrize(
    ("channel_type", "reason"),
    [
        ("instagram", "missing_instagram_business_account_id"),
        ("facebook", "missing_page_id"),
    ],
)
def test_meta_social_channel_readiness_false_without_required_credentials(db, tenant, channel_type, reason):
    channel = enable_social(db, tenant, channel_type, credentials={"page_access_token": "tenant-token"}, live_send_enabled=True)

    ready, actual_reason = OutboundService().channel_ready(channel)

    assert ready is False
    assert actual_reason == reason


@pytest.mark.parametrize("channel_type", ["instagram", "facebook"])
def test_meta_social_inbound_test_creates_customer_conversation_and_reply(db, tenant, channel_type):
    enable_social(db, tenant, channel_type, credentials={}, live_send_enabled=False)

    result = inbound(
        channel_type,
        tenant.slug,
        MetaSocialInboundTestRequest(sender_id="sender-123", display_name="Social Customer", message="what is the price?"),
        FakeRequest(),
        db,
    )

    assert result["reply"] == "The course costs 1500 SAR and lasts one month."
    assert result["state"] == "BOT_ACTIVE"
    assert result["handoff"] is False
    customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.phone == f"{channel_type}:{tenant.id}:sender-123").one()
    assert customer.name == "Social Customer"
    assert f"{channel_type}_sender_id:sender-123" in customer.tags_json
    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant.id, Conversation.channel_type == channel_type).one()
    assert str(conversation.id) == result["conversation_id"]
    inbound_message = db.query(Message).filter(Message.tenant_id == tenant.id, Message.conversation_id == conversation.id, Message.direction == "inbound").one()
    assert inbound_message.payload_json["source"] == f"{channel_type}_inbound_test"
    assert inbound_message.payload_json["sender_id"] == "sender-123"


def test_meta_social_same_sender_id_is_tenant_isolated(db, tenant):
    enable_social(db, tenant, "instagram", credentials={}, live_send_enabled=False)
    other = Tenant(slug="other-social", display_name="Other", timezone="Asia/Riyadh", default_lang="en", status="active")
    db.add(other)
    db.flush()
    enable_social(db, other, "instagram", credentials={}, live_send_enabled=False)

    first = receive_instagram_inbound_test(
        tenant.slug,
        MetaSocialInboundTestRequest(sender_id="same-sender", message="hello"),
        FakeRequest(host="10.0.0.1"),
        db=db,
    )
    second = receive_instagram_inbound_test(
        other.slug,
        MetaSocialInboundTestRequest(sender_id="same-sender", message="hello"),
        FakeRequest(host="10.0.0.2"),
        db=db,
    )

    assert first["conversation_id"] != second["conversation_id"]
    assert db.query(Customer).filter(Customer.phone.like("instagram:%:same-sender")).count() == 2
    assert db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.phone == f"instagram:{tenant.id}:same-sender").count() == 1
    assert db.query(Customer).filter(Customer.tenant_id == other.id, Customer.phone == f"instagram:{other.id}:same-sender").count() == 1


def test_meta_social_unknown_tenant_returns_safe_error(db):
    with pytest.raises(HTTPException) as exc:
        receive_facebook_inbound_test(
            "missing-tenant",
            MetaSocialInboundTestRequest(sender_id="sender-123", message="hello"),
            FakeRequest(),
            db=db,
        )
    assert exc.value.status_code == 404


def test_meta_social_disabled_channel_returns_safe_error(db, tenant):
    enable_social(db, tenant, "facebook", credentials={}, enabled=False, live_send_enabled=False)

    with pytest.raises(HTTPException) as exc:
        receive_facebook_inbound_test(
            tenant.slug,
            MetaSocialInboundTestRequest(sender_id="sender-123", message="hello"),
            FakeRequest(),
            db=db,
        )
    assert exc.value.status_code == 403


def test_meta_social_inbound_secret_requirement_when_configured(db, tenant):
    enable_social(db, tenant, "instagram", credentials={"webhook_secret": "tenant-social-secret"}, live_send_enabled=False)
    payload = MetaSocialInboundTestRequest(sender_id="sender-123", message="hello")

    with pytest.raises(HTTPException) as exc:
        receive_instagram_inbound_test(tenant.slug, payload, FakeRequest(), db=db)
    assert exc.value.status_code == 403

    result = receive_instagram_inbound_test(
        tenant.slug,
        payload,
        FakeRequest(headers={"X-Channel-Webhook-Secret": "tenant-social-secret"}),
        db=db,
    )
    assert result["conversation_id"]


@pytest.mark.parametrize("channel_type", ["instagram", "facebook"])
def test_meta_social_outbound_without_provider_identity_fails_safely(db, tenant, channel_type):
    enable_social(db, tenant, channel_type, credentials=meta_credentials(channel_type), live_send_enabled=True)
    customer = Customer(tenant_id=tenant.id, phone="0500000999", preferred_lang="en")
    db.add(customer)
    db.flush()
    conversation = Conversation(tenant_id=tenant.id, customer_id=customer.id, channel_type=channel_type, state="BOT_ACTIVE")
    db.add(conversation)
    db.commit()

    destination = CustomerChannelIdentityService().delivery_address(customer, channel_type)
    message = OutboundService().send_or_store(
        db,
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        channel_type=channel_type,
        destination=destination,
        text="Hello from support",
        intent_code="MANUAL_REPLY",
    )

    assert message.payload_json["send_status"] == "send_failed"
    assert message.payload_json["reason"] == "missing_provider_recipient"
    assert "page_access_token" not in str(message.payload_json)
