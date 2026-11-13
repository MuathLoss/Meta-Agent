from functools import cached_property
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENVS = {"production", "staging"}
PLACEHOLDER_MARKERS = ("changeme", "replace-me", "replace-with", "pending")
# Sign-in tokens are signed with HMAC-SHA256; a shorter key can be guessed offline.
MIN_APP_SECRET_KEY_LENGTH = 32
# Every channel the code can talk to. The product (spec v1.2, P06) sells only the first two;
# the rest stay in the code but are off unless ENABLED_CHANNELS lists them.
KNOWN_CHANNELS = ("web_chat", "whatsapp", "telegram", "email", "instagram", "facebook")
V1_CHANNELS = ("web_chat", "whatsapp")
STORAGE_BACKENDS = ("local",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_secret_key: str
    access_token_expire_minutes: int = 60
    database_url: str
    cors_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    frontend_url: str = "http://127.0.0.1:5173"
    default_timezone: str = "Asia/Riyadh"
    log_level: str = "INFO"
    tenant_channel_secret_key: str
    allow_unsigned_webhooks_in_dev: bool = True
    api_docs_enabled: bool | None = None
    email_polling_enabled: bool = False
    email_poll_interval_seconds: int = 60
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e4b"
    ollama_timeout_seconds: int = 10
    # Product scope (spec v1.2, Section 2.1).
    enabled_channels: str = ",".join(V1_CHANNELS)
    broadcasts_enabled: bool = False
    # Background jobs (spec v1.2, T07). Redis holds the queue only, never billing or usage state.
    redis_url: str = "redis://localhost:6379/0"
    worker_queue_name: str = "default"
    worker_heartbeat_seconds: int = 60
    # Private file storage (spec v1.2, T06). "local" keeps files on a backed-up volume.
    storage_backend: str = "local"
    storage_local_root: str = "./storage"

    @property
    def enabled_channel_set(self) -> frozenset[str]:
        # Read on every call (not cached) so a changed setting takes effect without a restart in tests.
        return frozenset(x.strip().lower() for x in self.enabled_channels.split(",") if x.strip())

    def channel_enabled(self, channel_type: str | None) -> bool:
        return (channel_type or "").strip().lower() in self.enabled_channel_set

    @cached_property
    def cors_allowed_origins_list(self) -> list[str]:
        origins = [x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()]
        if self.is_production_like and (not origins or "*" in origins):
            raise ValueError("CORS_ALLOWED_ORIGINS must be explicit in staging/production")
        return origins

    @property
    def is_production_like(self) -> bool:
        return self.app_env.strip().lower() in PRODUCTION_ENVS

    @property
    def api_docs_visible(self) -> bool:
        # The interactive API reference and schema are a development aid. They stay
        # off in staging/production unless API_DOCS_ENABLED is set on purpose.
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return not self.is_production_like

    def configured(self, value: object) -> bool:
        if value is None:
            return False
        text_value = str(value).strip()
        if not text_value:
            return False
        lowered = text_value.lower()
        return not any(marker in lowered for marker in PLACEHOLDER_MARKERS)

    def production_config_errors(self) -> list[str]:
        if not self.is_production_like:
            return []

        errors: list[str] = []
        required_secret_fields = {
            "APP_SECRET_KEY": self.app_secret_key,
            "DATABASE_URL": self.database_url,
            "TENANT_CHANNEL_SECRET_KEY": self.tenant_channel_secret_key,
        }
        for key, value in required_secret_fields.items():
            if not self.configured(value):
                errors.append(f"{key} is not safely configured")

        if self.configured(self.app_secret_key) and len(self.app_secret_key.strip()) < MIN_APP_SECRET_KEY_LENGTH:
            errors.append(f"APP_SECRET_KEY must be at least {MIN_APP_SECRET_KEY_LENGTH} characters")

        try:
            self.cors_allowed_origins_list
        except ValueError as exc:
            errors.append(str(exc))

        # Spec v1.2 acceptance criterion 16: these stay off in the production configuration.
        if self.broadcasts_enabled:
            errors.append("BROADCASTS_ENABLED must be false: bulk WhatsApp messaging is outside the product and Meta policy")
        if self.ollama_enabled:
            errors.append("OLLAMA_ENABLED must be false: a local model does not fit the pilot server")
        unknown = sorted(self.enabled_channel_set - set(KNOWN_CHANNELS))
        if unknown:
            errors.append("ENABLED_CHANNELS lists unknown channels: " + ", ".join(unknown))
        if self.storage_backend not in STORAGE_BACKENDS:
            errors.append("STORAGE_BACKEND must be one of: " + ", ".join(STORAGE_BACKENDS))

        return errors

    def validate_startup(self) -> None:
        errors = self.production_config_errors()
        if errors:
            raise RuntimeError("Production configuration is invalid: " + "; ".join(errors))

settings = Settings()
