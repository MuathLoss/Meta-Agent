from fastapi import Response
import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import routes_auth, routes_dashboard, routes_webhook
from app.core.rate_limit import RATE_LIMIT_DETAIL
from app.core.security import hash_password
from app.models.entities import ChannelConfig, TenantUserRole, User, WebhookEvent
from app.schemas.auth import LoginRequest, SignupBusinessRequest
from app.services.tenant_channel_service import TenantChannelService
from main import health


class FakeRequest:
    def __init__(self, payload: dict | None = None, *, host: str = "127.0.0.1", headers: dict | None = None):
        self.payload = payload or {}
        self.client = SimpleNamespace(host=host)
        self.headers = headers or {}
        self._body = json.dumps(self.payload).encode("utf-8")

    async def body(self) -> bytes:
        return self._body


def whatsapp_payload(provider_message_id: str = "wamid.rate") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone-test"},
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


def signed_headers(payload: dict, secret: str = "secret-test") -> dict:
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": signature}


def create_login_user(db, tenant, *, email: str = "rate@example.com", password: str = "Secret123!") -> User:
    user = User(email=email, full_name="Rate User", password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.commit()
    return user


def test_login_allows_normal_request_under_limit(db, tenant):
    create_login_user(db, tenant)

    result = routes_auth.login(
        LoginRequest(email="rate@example.com", password="Secret123!", tenant_slug=tenant.slug),
        request=FakeRequest(host="10.0.0.1"), response=Response(),
        db=db,
    )

    assert result.csrf_token
    assert result.user["email"] == "rate@example.com"


def test_login_returns_429_after_repeated_attempts(db, monkeypatch):
    monkeypatch.setattr(routes_auth, "LOGIN_RATE_LIMIT_MAX", 2)

    payload = LoginRequest(email="missing@example.com", password="wrong", tenant_slug=None)
    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            routes_auth.login(payload, request=FakeRequest(host="10.0.0.2"), response=Response(), db=db)
        assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        routes_auth.login(payload, request=FakeRequest(host="10.0.0.2"), response=Response(), db=db)

    assert exc.value.status_code == 429
    assert exc.value.detail == RATE_LIMIT_DETAIL


def test_login_rate_limit_does_not_leak_whether_email_exists(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_auth, "LOGIN_RATE_LIMIT_MAX", 1)
    create_login_user(db, tenant, email="known@example.com")

    for email in ["known@example.com", "unknown@example.com"]:
        payload = LoginRequest(email=email, password="wrong", tenant_slug=tenant.slug)
        with pytest.raises(HTTPException) as first:
            routes_auth.login(payload, request=FakeRequest(host="10.0.0.3"), response=Response(), db=db)
        with pytest.raises(HTTPException) as limited:
            routes_auth.login(payload, request=FakeRequest(host="10.0.0.3"), response=Response(), db=db)

        assert first.value.status_code == 401
        assert first.value.detail == "Invalid email or password"
        assert limited.value.status_code == 429
        assert limited.value.detail == RATE_LIMIT_DETAIL


def test_signup_business_returns_429_after_repeated_attempts(db, monkeypatch):
    monkeypatch.setattr(routes_auth, "SIGNUP_RATE_LIMIT_MAX", 1)

    first = SignupBusinessRequest(
        business_name="Rate One",
        tenant_slug="rate-one",
        admin_name="Admin One",
        admin_email="rate-one@example.com",
        admin_password="Secret123!",
    )
    second = SignupBusinessRequest(
        business_name="Rate Two",
        tenant_slug="rate-two",
        admin_name="Admin Two",
        admin_email="rate-two@example.com",
        admin_password="Secret123!",
    )

    assert routes_auth.signup(first, request=FakeRequest(host="10.0.0.4"), response=Response(), db=db).csrf_token
    with pytest.raises(HTTPException) as exc:
        routes_auth.signup(second, request=FakeRequest(host="10.0.0.4"), response=Response(), db=db)

    assert exc.value.status_code == 429
    assert exc.value.detail == RATE_LIMIT_DETAIL


def test_whatsapp_webhook_rate_limit_allows_normal_signed_request(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "production")

    def fake_handle_inbound(*args, **kwargs):
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)
    payload = whatsapp_payload("wamid.rate.ok")

    result = asyncio.run(
        routes_webhook.receive(
            FakeRequest(payload, host="10.0.0.5", headers=signed_headers(payload)),
            db=db,
        )
    )

    assert result == {"ok": True, "decision": {"status": "stored"}}


def test_whatsapp_webhook_returns_429_after_repeated_requests(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_webhook.settings, "app_env", "production")
    monkeypatch.setattr(routes_webhook, "WEBHOOK_RATE_LIMIT_MAX", 1)

    def fake_handle_inbound(*args, **kwargs):
        return {"status": "stored"}

    monkeypatch.setattr(routes_webhook.orchestrator, "handle_inbound", fake_handle_inbound)
    first_payload = whatsapp_payload("wamid.rate.first")
    second_payload = whatsapp_payload("wamid.rate.second")

    asyncio.run(routes_webhook.receive(FakeRequest(first_payload, host="10.0.0.6", headers=signed_headers(first_payload)), db=db))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes_webhook.receive(FakeRequest(second_payload, host="10.0.0.6", headers=signed_headers(second_payload)), db=db))

    assert exc.value.status_code == 429
    assert exc.value.detail == RATE_LIMIT_DETAIL
    assert db.query(WebhookEvent).filter(WebhookEvent.provider == "whatsapp").count() == 1


def test_telegram_webhook_path_still_works_under_limit(db, tenant, monkeypatch):
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
    payload = {"update_id": 2001, "message": {"chat": {"id": 99887766}, "text": "hello"}}

    result = asyncio.run(
        routes_webhook.receive_telegram(
            FakeRequest(payload, host="10.0.0.7", headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"}),
            db=db,
        )
    )

    assert result == {"ok": True, "decision": {"status": "telegram-stored"}}


def test_dashboard_preview_works_under_limit_and_returns_429_after_repeated_calls(db, tenant, monkeypatch):
    monkeypatch.setattr(routes_dashboard, "PREVIEW_RATE_LIMIT_MAX", 1)
    payload = routes_dashboard.PreviewInboundRequest(customer_phone="0500000000", text="السلام", channel_type="whatsapp")
    ctx = {"user": SimpleNamespace(id=123)}

    def fake_handle_inbound(*args, **kwargs):
        return {"status": "preview-stored"}

    monkeypatch.setattr(routes_dashboard.orchestrator, "handle_inbound", fake_handle_inbound)

    result = routes_dashboard.preview(payload, request=FakeRequest(host="10.0.0.8"), db=db, tenant=tenant, _=ctx)
    with pytest.raises(HTTPException) as exc:
        routes_dashboard.preview(payload, request=FakeRequest(host="10.0.0.8"), db=db, tenant=tenant, _=ctx)

    assert result == {"decision": {"status": "preview-stored"}}
    assert exc.value.status_code == 429
    assert exc.value.detail == RATE_LIMIT_DETAIL


def test_health_endpoint_is_not_rate_limited(monkeypatch):
    monkeypatch.setattr(routes_auth, "LOGIN_RATE_LIMIT_MAX", 1)
    for _ in range(5):
        assert health()["status"] == "ok"
