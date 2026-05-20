import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import routes_auth, routes_onboarding, routes_channels, routes_dashboard, routes_broadcasts, routes_webhook, routes_config, routes_operations, routes_runtime, routes_uat, routes_deployment, routes_acceptance, routes_imports
from app.core.config import settings
from app.core.db import SessionLocal
from app.services.email_polling_scheduler import EmailPollingBackgroundTask

logger = logging.getLogger(__name__)
settings.validate_startup()
email_polling_task: EmailPollingBackgroundTask | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global email_polling_task
    if settings.email_polling_enabled:
        email_polling_task = EmailPollingBackgroundTask()
        email_polling_task.start()
        logger.info("email polling background task started", extra={"interval_seconds": settings.email_poll_interval_seconds})
    else:
        logger.info("email polling background task disabled")
    try:
        yield
    finally:
        if email_polling_task:
            await email_polling_task.stop()
            logger.info("email polling background task stopped")


app = FastAPI(title="Configurable Multi-Tenant Business Agent Platform", version="0.7.0", lifespan=lifespan)
uploads_dir = Path(__file__).resolve().parent / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "Origin",
        "X-Tenant-Slug",
        "X-Hub-Signature-256",
        "X-Requested-With",
        "X-Channel-Webhook-Secret",
        "X-Telegram-Bot-Api-Secret-Token",
    ],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.app_env, "app": "business-agent-platform"}

@app.get("/health/ready")
def readiness():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception:
        logger.warning("database readiness check failed: database_error")
        return {"status": "not_ready", "database": "error", "error": "database_unavailable"}

app.include_router(routes_auth.router)
app.include_router(routes_onboarding.router)
app.include_router(routes_channels.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_broadcasts.router)
app.include_router(routes_webhook.router)
app.include_router(routes_config.router)
app.include_router(routes_operations.router)
app.include_router(routes_runtime.router)
app.include_router(routes_uat.router)
app.include_router(routes_deployment.router)
app.include_router(routes_imports.router)

app.include_router(routes_acceptance.router)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
