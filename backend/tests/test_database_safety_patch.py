import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import routes_uat, routes_webhook
from app.api.routes_dashboard import detail, inbox
from app.core.tenancy import get_current_tenant
from app.models.entities import AuditLog, ChannelConfig, Conversation, Customer, Tenant, User, WebhookEvent
from app.services.tenant_channel_service import TenantChannelService


class FakeRequest:
    def __init__(self, payload: dict, headers: dict | None = None):
        import json

        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


def whatsapp_payload(*, phone_number_id: str, provider_message_id: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "id": provider_message_id,
                                    "from": "966500000000",
                                    "text": {"body": "السلام"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def add_whatsapp_channel(db, tenant_id: int, *, phone_number_id: str, verify_token: str = "verify-test") -> ChannelConfig:
    svc = TenantChannelService()
    row = ChannelConfig(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        status="connected",
        public_config_json={"enabled": True, "phone_number_id": phone_number_id},
        encrypted_credentials=svc.encrypt_credentials({
            "verify_token": verify_token,
            "app_secret": "secret-test",
            "phone_number_id": phone_number_id,
            "access_token": "pending",
        }),
    )
    db.add(row)
    db.flush()
    return row


def test_dashboard_join_does_not_leak_cross_tenant_customer(db, tenant):
    other = Tenant(slug="other-dashboard", display_name="Other", timezone="Asia/Riyadh", default_lang="ar", status="active")
    db.add(other)
    db.flush()
    other_customer = Customer(tenant_id=other.id, phone="055-other", preferred_lang="ar")
    db.add(other_customer)
    db.flush()
    bad_conversation = Conversation(
        tenant_id=tenant.id,
        customer_id=other_customer.id,
        channel_type="whatsapp",
        state="BOT_ACTIVE",
    )
    db.add(bad_conversation)
    db.commit()

    rows = inbox(state=None, owner_ref=None, db=db, tenant=tenant, _={})
    assert all(row["customer_id"] != other_customer.id for row in rows)

    with pytest.raises(HTTPException) as exc:
        detail(conversation_id=bad_conversation.id, db=db, tenant=tenant, _={})
    assert exc.value.status_code == 404


def test_webhook_duplicate_for_one_tenant_does_not_suppress_another_tenant(db, tenant, monkeypatch):
    other = Tenant(slug="other-webhook", display_name="Other", timezone="Asia/Riyadh", default_lang="ar", status="active")
    db.add(other)
    db.flush()
    add_whatsapp_channel(db, other.id, phone_number_id="phone-other", verify_token="verify-other")
    db.commit()

    def fake_handle_inbound(*args, **kwargs):
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)

    first = asyncio.run(routes_webhook.receive(FakeRequest(whatsapp_payload(phone_number_id="phone-test", provider_message_id="wamid.same")), db=db))
    second = asyncio.run(routes_webhook.receive(FakeRequest(whatsapp_payload(phone_number_id="phone-other", provider_message_id="wamid.same")), db=db))

    assert first["ok"] is True
    assert second["ok"] is True
    assert "duplicate" not in second
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 2


def test_ambiguous_whatsapp_channel_resolution_fails_closed(db, tenant, monkeypatch):
    other = Tenant(slug="other-ambiguous", display_name="Other", timezone="Asia/Riyadh", default_lang="ar", status="active")
    db.add(other)
    db.flush()
    add_whatsapp_channel(db, other.id, phone_number_id="phone-test", verify_token="verify-other")
    db.commit()

    called = False

    def fake_handle_inbound(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)

    result = asyncio.run(routes_webhook.receive(FakeRequest(whatsapp_payload(phone_number_id="phone-test", provider_message_id="wamid.ambiguous")), db=db))

    assert result == {"ok": True, "ignored": "ambiguous_tenant_channel"}
    assert called is False
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 0


def test_uat_fixture_access_is_blocked_outside_dev_or_test(monkeypatch):
    monkeypatch.setattr(routes_uat.settings, "app_env", "production")

    with pytest.raises(HTTPException) as exc:
        routes_uat.require_uat_fixture_access(
            ctx={"user": SimpleNamespace(is_platform_admin=True)},
            x_uat_fixture_access="true",
        )

    assert exc.value.status_code == 403


def test_uat_fixture_access_requires_explicit_test_permission_in_dev(monkeypatch):
    monkeypatch.setattr(routes_uat.settings, "app_env", "development")

    with pytest.raises(HTTPException) as exc:
        routes_uat.require_uat_fixture_access(
            ctx={"user": SimpleNamespace(is_platform_admin=False)},
            x_uat_fixture_access=None,
        )
    assert exc.value.status_code == 403

    result = routes_uat.require_uat_fixture_access(
        ctx={"user": SimpleNamespace(is_platform_admin=False)},
        x_uat_fixture_access="true",
    )
    assert result["user"].is_platform_admin is False


def test_platform_admin_tenant_access_requires_reason_and_is_audited(db, tenant):
    admin = User(
        email="platform-audit@example.com",
        full_name="Platform Admin",
        password_hash="hash",
        is_platform_admin=True,
    )
    db.add(admin)
    db.commit()

    payload = {"sub": str(admin.id)}
    with pytest.raises(HTTPException) as exc:
        get_current_tenant(x_tenant_slug=tenant.slug, x_support_access_reason=None, payload=payload, db=db)
    assert exc.value.status_code == 403

    resolved = get_current_tenant(
        x_tenant_slug=tenant.slug,
        x_support_access_reason="support investigation",
        payload=payload,
        db=db,
    )

    assert resolved.id == tenant.id
    audit = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id, AuditLog.actor_user_id == admin.id, AuditLog.action == "support.tenant_access").one()
    assert audit.details_json["reason"] == "support investigation"
