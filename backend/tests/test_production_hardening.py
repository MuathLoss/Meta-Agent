from fastapi.testclient import TestClient

import main
from app.core.config import Settings


def make_settings(**overrides) -> Settings:
    defaults = {
        "app_env": "development",
        "app_secret_key": "local-secret",
        "database_url": "sqlite+pysqlite:///:memory:",
        "tenant_channel_secret_key": "local-tenant-channel-secret",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def test_production_cors_wildcard_is_rejected():
    settings = make_settings(
        app_env="production",
        cors_allowed_origins="*",
        app_secret_key="real-production-secret",
        database_url="postgresql+psycopg://user:pass@db.internal/app",
        tenant_channel_secret_key="real-tenant-channel-secret",
    )

    errors = settings.production_config_errors()

    assert any("CORS_ALLOWED_ORIGINS" in error for error in errors)
    assert "db.internal" not in str(errors)
    assert "real-production-secret" not in str(errors)


def test_development_cors_wildcard_is_allowed():
    settings = make_settings(app_env="development", cors_allowed_origins="*")

    assert settings.cors_allowed_origins_list == ["*"]
    assert settings.production_config_errors() == []


def test_placeholder_production_secret_is_reported_safely():
    settings = make_settings(
        app_env="staging",
        cors_allowed_origins="https://dashboard.example.test",
        app_secret_key="replace-me",
        database_url="postgresql+psycopg://user:pass@db.internal/app",
        tenant_channel_secret_key="real-tenant-channel-secret",
    )

    errors = settings.production_config_errors()

    assert "APP_SECRET_KEY is not safely configured" in errors
    assert "replace-me" not in str(errors)
    assert "db.internal" not in str(errors)


def test_readiness_db_failure_response_is_safe(monkeypatch):
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement):
            raise RuntimeError("postgresql://user:password@db.internal:5432/app connection refused")

    monkeypatch.setattr(main, "SessionLocal", lambda: BrokenSession())

    result = main.readiness()
    assert result.status_code == 503
    import json
    response = json.loads(result.body)

    assert response == {"status": "not_ready", "database": "error", "error": "database_unavailable"}
    assert "password" not in str(response)
    assert "db.internal" not in str(response)
    assert "postgresql://" not in str(response)


def test_security_headers_are_present_on_api_response():
    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_cors_preflight_allows_frontend_tenant_header():
    response = TestClient(main.app).options(
        "/tenants/current",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type,x-tenant-slug",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "X-Tenant-Slug" in response.headers["access-control-allow-headers"]
