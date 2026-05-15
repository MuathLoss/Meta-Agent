from __future__ import annotations

from dataclasses import dataclass
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import ChannelConfig, Tenant
from app.services.tenant_channel_service import TenantChannelService

router = APIRouter(prefix="/deployment", tags=["deployment"])
channel_service = TenantChannelService()


@dataclass(frozen=True)
class EnvItem:
    key: str
    purpose: str
    secret: bool = False


PLATFORM_ENV_ITEMS = [
    EnvItem("APP_ENV", "development / staging / production mode"),
    EnvItem("APP_SECRET_KEY", "JWT signing secret", True),
    EnvItem("JWT_REFRESH_SECRET_KEY", "refresh-token signing secret", True),
    EnvItem("DATABASE_URL", "PostgreSQL connection string", True),
    EnvItem("CORS_ALLOWED_ORIGINS", "allowed frontend origins"),
    EnvItem("FRONTEND_URL", "deployed frontend URL"),
    EnvItem("DEFAULT_TIMEZONE", "default platform timezone"),
    EnvItem("LOG_LEVEL", "application logging level"),
    EnvItem("TENANT_CHANNEL_SECRET_KEY", "Fernet key for tenant channel credentials", True),
    EnvItem("ALLOW_UNSIGNED_WEBHOOKS_IN_DEV", "dev-only webhook signature bypass"),
]


def _configured(value: object) -> bool:
    if value is None:
        return False
    text_value = str(value).strip()
    if not text_value:
        return False
    lowered = text_value.lower()
    return not any(marker in lowered for marker in ["replace-with", "pending", "changeme"])


@router.get("/environment")
def environment_status(
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    data = []
    for item in PLATFORM_ENV_ITEMS:
        value = getattr(settings, item.key.lower(), None)
        data.append({
            "key": item.key,
            "purpose": item.purpose,
            "secret": item.secret,
            "configured": _configured(value),
            "value_preview": "configured" if item.secret and _configured(value) else ("missing" if not _configured(value) else str(value)),
        })
    return {"items": data}


@router.get("/checklist")
def deployment_checklist(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    whatsapp: ChannelConfig | None = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "whatsapp")
        .first()
    )
    creds = channel_service.credentials(whatsapp) if whatsapp else {}
    public_config = whatsapp.public_config_json if whatsapp else {}
    live_send_enabled = bool(public_config.get("live_send_enabled"))

    items = [
        {"key": "database", "label": "Database connection works", "passed": db_ok},
        {"key": "tenant_active", "label": "Tenant workspace is active/published", "passed": tenant.status == "active", "detail": tenant.status},
        {"key": "tenant_channel_model", "label": "WhatsApp exists as tenant-scoped channel config", "passed": whatsapp is not None},
        {"key": "verify_token", "label": "Tenant WhatsApp verify token is stored in encrypted channel credentials", "passed": _configured(creds.get("verify_token"))},
        {"key": "app_secret", "label": "Tenant WhatsApp app secret is stored in encrypted channel credentials", "passed": _configured(creds.get("app_secret"))},
        {"key": "phone_number_id", "label": "Tenant WhatsApp phone_number_id is configured", "passed": _configured(creds.get("phone_number_id") or public_config.get("phone_number_id"))},
        {"key": "access_token", "label": "Tenant WhatsApp production access token is configured", "passed": _configured(creds.get("access_token"))},
        {"key": "live_send", "label": "Live outbound WhatsApp sending is explicitly enabled", "passed": live_send_enabled, "detail": "Keep false until real academy credentials/templates are approved."},
        {"key": "frontend_url", "label": "Frontend URL configured", "passed": _configured(settings.frontend_url), "detail": settings.frontend_url},
        {"key": "staging_required", "label": "Staging/UAT must pass before production go-live", "passed": settings.app_env in {"staging", "production"}, "detail": settings.app_env},
    ]
    passed = sum(1 for item in items if item["passed"])
    return {
        "tenant": tenant.slug,
        "environment": settings.app_env,
        "passed": passed,
        "total": len(items),
        "ready_for_live_whatsapp": passed == len(items),
        "items": items,
    }


@router.get("/whatsapp-go-live-package")
def whatsapp_go_live_package(
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    return {
        "tenant": tenant.slug,
        "required_items": [
            {"key": "business_phone_number", "label": "Final WhatsApp Business phone number", "provided_by": "academy/client"},
            {"key": "waba_id", "label": "WhatsApp Business Account ID", "provided_by": "academy/client or Meta admin"},
            {"key": "phone_number_id", "label": "Meta phone number ID", "provided_by": "Meta app setup"},
            {"key": "production_access_token", "label": "Production system-user access token", "provided_by": "Meta app setup"},
            {"key": "app_secret", "label": "Meta app secret for webhook signature validation", "provided_by": "Meta app setup"},
            {"key": "verify_token", "label": "Tenant verify token for webhook handshake", "provided_by": "platform admin chooses/stores per tenant"},
            {"key": "approved_templates", "label": "Approved template names and languages", "provided_by": "academy/client + Meta approval"},
            {"key": "public_callback_url", "label": "Public HTTPS callback URL", "provided_by": "deployment"},
        ],
        "rule": "Do not place these as one global WhatsApp config in .env. Store them in this tenant's channel settings.",
    }
