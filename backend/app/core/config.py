from functools import cached_property
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_secret_key: str
    jwt_refresh_secret_key: str
    access_token_expire_minutes: int = 60
    refresh_token_expire_minutes: int = 10080
    database_url: str
    cors_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    frontend_url: str = "http://127.0.0.1:5173"
    default_timezone: str = "Asia/Riyadh"
    log_level: str = "INFO"
    tenant_channel_secret_key: str
    allow_unsigned_webhooks_in_dev: bool = True
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e4b"
    ollama_timeout_seconds: int = 10

    @cached_property
    def cors_allowed_origins_list(self) -> list[str]:
        return [x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()]

settings = Settings()
