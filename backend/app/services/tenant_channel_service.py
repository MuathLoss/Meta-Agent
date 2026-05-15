from sqlalchemy.orm import Session
from app.core.redaction import REDACTED, redact_string
from app.core.crypto import decrypt_dict, encrypt_dict
from app.models.entities import ChannelConfig


class DuplicateProviderChannelError(ValueError):
    pass


class UnsafePublicConfigError(ValueError):
    pass


PUBLIC_CONFIG_SECRET_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "bot_token",
    "app_secret",
    "client_secret",
    "verify_token",
    "password",
    "api_key",
    "secret",
    "authorization",
    "signature",
    "x-hub-signature-256",
    "database_url",
    "webhook_url_with_token",
}
PUBLIC_CONFIG_SECRET_KEY_PARTS = ("token", "secret", "password", "signature", "authorization")


def public_config_key_is_secret_like(key: str) -> bool:
    normalized = key.strip().lower().replace("_", "-")
    underscore = normalized.replace("-", "_")
    return underscore in PUBLIC_CONFIG_SECRET_KEYS or any(part in underscore for part in PUBLIC_CONFIG_SECRET_KEY_PARTS)


def public_config_value_is_secret_like(value: object) -> bool:
    return isinstance(value, str) and redact_string(value) != value


def sanitize_public_config(public_config: dict | None) -> dict:
    def sanitize(value):
        if isinstance(value, dict):
            return {
                key: REDACTED if public_config_key_is_secret_like(str(key)) else sanitize(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if isinstance(value, tuple):
            return [sanitize(item) for item in value]
        if public_config_value_is_secret_like(value):
            return REDACTED
        return value

    return sanitize(public_config or {})


def validate_public_config(public_config: dict | None) -> None:
    def walk(value, path: str = "public_config") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if public_config_key_is_secret_like(str(key)):
                    raise UnsafePublicConfigError("public_config contains credential-like fields; put secrets in credentials instead")
                walk(item, f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        if public_config_value_is_secret_like(value):
            raise UnsafePublicConfigError("public_config contains credential-like values; put secrets in credentials instead")

    walk(public_config or {})


class TenantChannelService:
    def routing_keys(self, channel_type: str, public_config: dict | None) -> tuple[str | None, str | None]:
        config = public_config or {}
        if channel_type == "whatsapp":
            provider_channel_id = config.get("provider_channel_id") or config.get("phone_number_id")
            provider_account_id = config.get("provider_account_id") or config.get("waba_id")
            return provider_channel_id, provider_account_id
        return config.get("provider_channel_id"), config.get("provider_account_id")

    def list(self, db: Session, tenant_id: int):
        return (
            db.query(ChannelConfig)
            .filter(ChannelConfig.tenant_id == tenant_id)
            .order_by(ChannelConfig.channel_type)
            .all()
        )

    def get(self, db: Session, tenant_id: int, channel_type: str):
        return (
            db.query(ChannelConfig)
            .filter(
                ChannelConfig.tenant_id == tenant_id,
                ChannelConfig.channel_type == channel_type,
            )
            .first()
        )

    def encrypt_credentials(self, credentials: dict) -> str:
        return encrypt_dict(credentials or {})

    def decrypt_credentials(self, encrypted_credentials: str | None) -> dict:
        return decrypt_dict(encrypted_credentials)

    def upsert(
        self,
        db: Session,
        tenant_id: int,
        channel_type: str,
        status: str,
        public_config: dict,
        credentials: dict,
    ):
        validate_public_config(public_config)
        row = self.get(db, tenant_id, channel_type)
        if not row:
            row = ChannelConfig(tenant_id=tenant_id, channel_type=channel_type)
            db.add(row)
        provider_channel_id, provider_account_id = self.routing_keys(channel_type, public_config)
        if provider_channel_id:
            duplicate = (
                db.query(ChannelConfig)
                .filter(
                    ChannelConfig.channel_type == channel_type,
                    ChannelConfig.provider_channel_id == str(provider_channel_id),
                    ChannelConfig.tenant_id != tenant_id,
                )
                .first()
            )
            if duplicate:
                raise DuplicateProviderChannelError("provider_channel_id is already configured for this channel_type")
        row.status = status
        row.provider_channel_id = str(provider_channel_id) if provider_channel_id else None
        row.provider_account_id = str(provider_account_id) if provider_account_id else None
        row.public_config_json = public_config or {}
        if credentials:
            row.encrypted_credentials = self.encrypt_credentials(credentials)
        db.flush()
        return row

    def credentials(self, row: ChannelConfig) -> dict:
        return self.decrypt_credentials(row.encrypted_credentials)
