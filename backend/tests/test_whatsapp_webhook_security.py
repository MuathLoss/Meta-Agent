import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException

from app.api import routes_webhook
from app.api.routes_dashboard import preview
from app.models.entities import ChannelConfig, Tenant, WebhookEvent
from app.services.tenant_channel_service import TenantChannelService


class FakeRequest:
    def __init__(self, payload: dict, headers: dict | None = None):
        from types import SimpleNamespace

        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}
        self.client = SimpleNamespace(host="127.0.0.1")

    async def body(self) -> bytes:
        return self._body


def whatsapp_payload(*, phone_number_id: str = "phone-test", provider_message_id: str = "wamid.security") -> dict:
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


def signed_headers(payload: dict, secret: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": signature}


def set_whatsapp_app_secret(db, tenant_id: int, app_secret: str | None) -> None:
    svc = TenantChannelService()
    channel = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel_type == "whatsapp")
        .one()
    )
    channel.encrypted_credentials = svc.encrypt_credentials(
        {
            "verify_token": "verify-test",
            "app_secret": app_secret,
            "phone_number_id": "phone-test",
            "access_token": "pending",
        }
    )
    db.commit()


def test_production_whatsapp_webhook_without_signature_is_rejected(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "production")
    called = False

    def fake_handle_inbound(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes_webhook.receive(FakeRequest(whatsapp_payload()), db=db))

    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid WhatsApp webhook signature"
    assert called is False
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 0


def test_staging_whatsapp_webhook_with_invalid_signature_is_rejected(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "staging")
    called = False

    def fake_handle_inbound(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            routes_webhook.receive(
                FakeRequest(whatsapp_payload(provider_message_id="wamid.invalid"), headers={"X-Hub-Signature-256": "sha256=bad"}),
                db=db,
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid WhatsApp webhook signature"
    assert called is False
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 0


def test_production_whatsapp_webhook_with_pending_app_secret_is_rejected(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "production")
    set_whatsapp_app_secret(db, tenant.id, "pending")
    called = False

    def fake_handle_inbound(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes_webhook.receive(FakeRequest(whatsapp_payload(provider_message_id="wamid.pending")), db=db))

    assert exc.value.status_code == 403
    assert exc.value.detail == "WhatsApp webhook app secret is not configured"
    assert called is False
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 0


def test_development_unsigned_whatsapp_webhook_bypass_still_works(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "development")
    monkeypatch.setattr(routes_webhook.settings, "allow_unsigned_webhooks_in_dev", True)

    def fake_handle_inbound(*args, **kwargs):
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)

    result = asyncio.run(routes_webhook.receive(FakeRequest(whatsapp_payload(provider_message_id="wamid.dev")), db=db))

    assert result == {"ok": True, "decision": {"status": "stored"}}
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 1


def test_development_invalid_whatsapp_signature_is_not_bypassed(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "development")
    monkeypatch.setattr(routes_webhook.settings, "allow_unsigned_webhooks_in_dev", True)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            routes_webhook.receive(
                FakeRequest(whatsapp_payload(provider_message_id="wamid.dev-invalid"), headers={"X-Hub-Signature-256": "sha256=bad"}),
                db=db,
            )
        )

    assert exc.value.status_code == 403
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 0


def test_valid_signed_whatsapp_webhook_passes_in_production(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "production")
    payload = whatsapp_payload(provider_message_id="wamid.signed")

    def fake_handle_inbound(*args, **kwargs):
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)

    result = asyncio.run(routes_webhook.receive(FakeRequest(payload, headers=signed_headers(payload, "secret-test")), db=db))

    assert result == {"ok": True, "decision": {"status": "stored"}}
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 1


def test_telegram_webhook_path_still_works(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "production")
    svc = TenantChannelService()
    db.add(
        ChannelConfig(
            tenant_id=tenant.id,
            channel_type="telegram",
            status="connected",
            public_config_json={"enabled": True},
            encrypted_credentials=svc.encrypt_credentials({"bot_token": "123:abc", "secret_token": "telegram-secret"}),
        )
    )
    db.commit()

    def fake_handle_inbound(*args, **kwargs):
        return {"status": "telegram-stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)
    payload = {"update_id": 1001, "message": {"chat": {"id": 99887766}, "text": "hello"}}

    result = asyncio.run(
        routes_webhook.receive_telegram(
            FakeRequest(payload, headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"}),
            db=db,
        )
    )

    assert result == {"ok": True, "decision": {"status": "telegram-stored"}}
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "telegram").count() == 1


def test_dashboard_preview_inbound_still_works(db, tenant, monkeypatch):
    def fake_handle_inbound(*args, **kwargs):
        return {"status": "preview-stored"}

    monkeypatch.setattr("app.api.routes_dashboard.orchestrator.handle_inbound", fake_handle_inbound)

    result = preview(
        payload=type("Payload", (), {"customer_phone": "0500000000", "text": "السلام", "channel_type": "whatsapp"})(),
        request=FakeRequest({}),
        db=db,
        tenant=tenant,
        _={},
    )

    assert result == {"decision": {"status": "preview-stored"}}
