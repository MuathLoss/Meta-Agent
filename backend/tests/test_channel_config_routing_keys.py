import pytest

from app.api import routes_channels, routes_webhook
from app.models.entities import ChannelConfig, Tenant
from app.services.tenant_channel_service import DuplicateProviderChannelError, TenantChannelService


def test_channel_config_update_populates_whatsapp_routing_keys(db, tenant):
    service = TenantChannelService()

    row = service.upsert(
        db,
        tenant.id,
        "whatsapp",
        "connected",
        {"enabled": True, "phone_number_id": "phone-updated", "waba_id": "waba-updated"},
        {},
    )

    assert row.provider_channel_id == "phone-updated"
    assert row.provider_account_id == "waba-updated"
    assert row.public_config_json["phone_number_id"] == "phone-updated"
    assert row.public_config_json["waba_id"] == "waba-updated"


def test_webhook_resolution_prefers_provider_channel_id_without_decrypting(db, tenant, monkeypatch):
    channel = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "whatsapp")
        .one()
    )
    channel.provider_channel_id = "phone-indexed"
    channel.public_config_json = {"enabled": True}
    db.commit()

    def fail_if_fallback_decrypts(*args, **kwargs):
        raise AssertionError("indexed webhook resolution should not decrypt credentials")

    monkeypatch.setattr(routes_webhook.channel_service, "credentials", fail_if_fallback_decrypts)

    resolved = routes_webhook._resolve_channel_by_phone_number_id(db, "phone-indexed")

    assert resolved is not None
    assert resolved.id == channel.id


def test_duplicate_provider_channel_id_same_channel_type_is_blocked(db, tenant):
    service = TenantChannelService()
    first = service.upsert(
        db,
        tenant.id,
        "whatsapp",
        "connected",
        {"enabled": True, "phone_number_id": "phone-duplicate"},
        {},
    )
    other = Tenant(slug="other-routing", display_name="Other", timezone="Asia/Riyadh", default_lang="ar", status="active")
    db.add(other)
    db.flush()

    with pytest.raises(DuplicateProviderChannelError):
        service.upsert(
            db,
            other.id,
            "whatsapp",
            "connected",
            {"enabled": True, "phone_number_id": "phone-duplicate"},
            {},
        )

    assert first.provider_channel_id == "phone-duplicate"


def test_channel_config_response_does_not_expose_encrypted_credentials(db, tenant):
    row = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "whatsapp")
        .one()
    )
    row.provider_channel_id = "phone-response"
    row.provider_account_id = "waba-response"

    response = routes_channels.ser(row).model_dump()

    assert response["provider_channel_id"] == "phone-response"
    assert response["provider_account_id"] == "waba-response"
    assert response["has_credentials"] is True
    assert "encrypted_credentials" not in response
