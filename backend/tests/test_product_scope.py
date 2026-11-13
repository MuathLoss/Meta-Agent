"""Spec v1.2, Section 2.1: only the website widget and WhatsApp are on; broadcasts are off."""
import pytest
from fastapi.testclient import TestClient

import main
from app.core.config import Settings, settings
from app.core.features import channel_named_in_path
from app.models.entities import ChannelConfig
from app.services.outbound_service import OutboundService


@pytest.fixture()
def product_defaults(monkeypatch):
    # Undo conftest's "everything on" so these tests see the shipped defaults.
    monkeypatch.setattr(settings, "enabled_channels", "web_chat,whatsapp")
    monkeypatch.setattr(settings, "broadcasts_enabled", False)


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "app_secret_key": "p" * 40,
        "database_url": "postgresql+psycopg://user:pass@db.internal/app",
        "tenant_channel_secret_key": "real-tenant-channel-secret",
        "cors_allowed_origins": "https://app.example.test",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_shipped_defaults_are_the_v1_scope():
    defaults = make_settings(app_env="development")
    assert defaults.enabled_channel_set == {"web_chat", "whatsapp"}
    assert defaults.broadcasts_enabled is False
    assert defaults.ollama_enabled is False


def test_features_endpoint_reports_the_v1_scope(product_defaults):
    response = TestClient(main.app).get("/features")
    assert response.status_code == 200
    assert response.json() == {"enabled_channels": ["web_chat", "whatsapp"], "broadcasts": False}


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/channels/telegram/webhook"),
        ("post", "/channels/telegram/webhook/123:abc"),
        ("get", "/channels/instagram/webhook"),
        ("post", "/channels/facebook/webhook"),
        ("post", "/channels/email/some-school/inbound-test"),
        ("post", "/channels/instagram/some-school/inbound-test"),
        ("put", "/channels/telegram/settings"),
        ("post", "/channels/telegram/verify"),
        ("post", "/channels/email/some-school/poll-once"),
        ("get", "/broadcasts"),
        ("post", "/broadcasts"),
        ("post", "/broadcasts/1/send"),
    ],
)
def test_switched_off_routes_answer_404(product_defaults, method, path):
    response = getattr(TestClient(main.app), method)(path)
    assert response.status_code == 404


def test_whatsapp_webhook_stays_reachable(product_defaults):
    response = TestClient(main.app).get("/channels/whatsapp/webhook")
    assert response.status_code == 200
    assert response.json() == {"ok": False}


def test_outbound_never_sends_through_a_switched_off_channel(product_defaults):
    telegram = ChannelConfig(tenant_id=1, channel_type="telegram", status="connected", public_config_json={"enabled": True, "live_send_enabled": True})
    assert OutboundService().channel_ready(telegram) == (False, "channel_not_in_product")


def test_outbound_still_checks_whatsapp_normally(product_defaults):
    whatsapp = ChannelConfig(tenant_id=1, channel_type="whatsapp", status="connected", public_config_json={"enabled": True, "live_send_enabled": False})
    assert OutboundService().channel_ready(whatsapp) == (False, "live_send_not_enabled")


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/channels/telegram/webhook", "telegram"),
        ("/api/channels/web-chat/school-a/message", "web_chat"),
        ("/channels/whatsapp/webhook", "whatsapp"),
        ("/channels/readiness", None),
        ("/channels/test-console/message", None),
        ("/channels", None),
        ("/broadcasts", None),
    ],
)
def test_channel_is_read_from_the_path(path, expected):
    assert channel_named_in_path(path) == expected


def test_clean_production_config_has_no_errors():
    assert make_settings().production_config_errors() == []


def test_production_refuses_broadcasts_and_ollama():
    errors = make_settings(broadcasts_enabled=True, ollama_enabled=True).production_config_errors()
    assert any("BROADCASTS_ENABLED" in error for error in errors)
    assert any("OLLAMA_ENABLED" in error for error in errors)


def test_production_refuses_unknown_channels_and_storage():
    errors = make_settings(enabled_channels="web_chat,whatsapp,sms", storage_backend="s3").production_config_errors()
    assert any("sms" in error for error in errors)
    assert any("STORAGE_BACKEND" in error for error in errors)
