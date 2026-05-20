from functools import cached_property
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENVS = {"production", "staging"}
PLACEHOLDER_MARKERS = ("changeme", "replace-me", "replace-with", "pending")


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
    email_polling_enabled: bool = False
    email_poll_interval_seconds: int = 60
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e4b"
    ollama_timeout_seconds: int = 10

    @cached_property
    def cors_allowed_origins_list(self) -> list[str]:
        origins = [x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()]
        if self.is_production_like and (not origins or "*" in origins):
            raise ValueError("CORS_ALLOWED_ORIGINS must be explicit in staging/production")
        return origins

    @property
    def is_production_like(self) -> bool:
        return self.app_env.strip().lower() in PRODUCTION_ENVS

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

        try:
            self.cors_allowed_origins_list
        except ValueError as exc:
            errors.append(str(exc))

        return errors

    def validate_startup(self) -> None:
        errors = self.production_config_errors()
        if errors:
            raise RuntimeError("Production configuration is invalid: " + "; ".join(errors))

settings = Settings()
