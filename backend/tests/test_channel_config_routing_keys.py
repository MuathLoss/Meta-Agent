import pytest

from app.api import routes_channels, routes_webhook
from app.schemas.channels import ChannelConfigRequest
from app.models.entities import ChannelConfig, Tenant
from app.services.tenant_channel_service import DuplicateProviderChannelError, TenantChannelService, UnsafePublicConfigError


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


def test_public_config_with_token_like_key_is_rejected(db, tenant):
    service = TenantChannelService()

    with pytest.raises(UnsafePublicConfigError):
        service.upsert(
            db,
            tenant.id,
            "telegram",
            "connected",
            {"enabled": True, "bot_token": "123:secret"},
            {},
        )

    row = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "telegram").first()
    assert row is None


def test_public_config_with_nested_secret_like_key_is_rejected(db, tenant):
    service = TenantChannelService()

    with pytest.raises(UnsafePublicConfigError):
        service.upsert(
            db,
            tenant.id,
            "whatsapp",
            "connected",
            {"enabled": True, "metadata": {"client_secret": "secret-value"}},
            {},
        )


def test_public_config_with_tokenized_url_value_is_rejected(db, tenant):
    service = TenantChannelService()

    with pytest.raises(UnsafePublicConfigError):
        service.upsert(
            db,
            tenant.id,
            "webchat",
            "connected",
            {"enabled": True, "webhook_url": "https://example.test/hook?access_token=secret-token"},
            {},
        )


def test_channel_update_returns_safe_error_for_unsafe_public_config(db, tenant):
    with pytest.raises(Exception) as exc:
        routes_channels.update(
            "telegram",
            ChannelConfigRequest(public_config={"enabled": True, "access_token": "secret-token"}, credentials={}),
            db=db,
            tenant=tenant,
            _={},
        )

    assert getattr(exc.value, "status_code", None) == 400
    assert "secret-token" not in getattr(exc.value, "detail", "")


def test_channel_response_redacts_unsafe_existing_public_config(db, tenant):
    row = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "whatsapp")
        .one()
    )
    row.public_config_json = {
        "enabled": True,
        "phone_number_id": "phone-safe-routing-id",
        "access_token": "old-token",
        "nested": {
            "webhook_url": "https://example.test/hook?signature=secret",
            "label": "Main inbox",
        },
    }
    db.flush()

    response = routes_channels.ser(row).model_dump()

    assert response["public_config"]["enabled"] is True
    assert response["public_config"]["phone_number_id"] == "phone-safe-routing-id"
    assert response["public_config"]["access_token"] == "[REDACTED]"
    assert response["public_config"]["nested"]["webhook_url"] == "[REDACTED]"
    assert response["public_config"]["nested"]["label"] == "Main inbox"
    assert "old-token" not in str(response)


def test_valid_safe_public_config_still_works_and_has_credentials_is_unchanged(db, tenant):
    response = routes_channels.update(
        "telegram",
        ChannelConfigRequest(
            status="connected",
            public_config={"enabled": True, "live_send_enabled": False, "provider_display_name": "Support bot"},
            credentials={"bot_token": "telegram-secret-token"},
        ),
        db=db,
        tenant=tenant,
        _={},
    ).model_dump()

    assert response["public_config"] == {"enabled": True, "live_send_enabled": False, "provider_display_name": "Support bot"}
    assert response["has_credentials"] is True
    assert "encrypted_credentials" not in response
    assert "telegram-secret-token" not in str(response)
