from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import routes_auth, routes_onboarding, routes_channels, routes_dashboard, routes_broadcasts, routes_webhook, routes_config, routes_operations, routes_runtime, routes_uat, routes_deployment, routes_acceptance, routes_imports, routes_team, routes_widget
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.features import channel_enabled, public_features, require_broadcasts_enabled, require_channel_route_enabled
from app.jobs.periodic import worker_heartbeat_age_seconds
from app.jobs.queue import redis_reachable
from app.services.email_polling_scheduler import EmailPollingBackgroundTask

logger = logging.getLogger(__name__)
settings.validate_startup()
email_polling_task: EmailPollingBackgroundTask | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global email_polling_task
    if settings.email_polling_enabled and channel_enabled("email"):
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


api_docs_visible = settings.api_docs_visible
app = FastAPI(
    title="Configurable Multi-Tenant Business Agent Platform",
    version="0.7.0",
    lifespan=lifespan,
    docs_url="/docs" if api_docs_visible else None,
    redoc_url="/redoc" if api_docs_visible else None,
    openapi_url="/openapi.json" if api_docs_visible else None,
)
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
        "X-CSRF-Token",
        "X-Support-Access-Reason",
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
    # Pages that state their own allowed embedders (the website chat frame) are framed
    # only where that policy allows; everything else may never be framed.
    if "frame-ancestors" not in response.headers.get("Content-Security-Policy", ""):
        response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.app_env, "app": "business-agent-platform"}

@app.get("/health/ready")
def readiness():
    body: dict = {"status": "ready", "database": "ok"}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            body["row_level_security"] = row_level_security_status(db)
    except Exception:
        logger.warning("database readiness check failed: database_error")
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "error", "error": "database_unavailable"})

    # The job queue is required on staging/production. Locally the API still starts without it.
    queue_ok = redis_reachable()
    body["queue"] = "ok" if queue_ok else "error"
    # Reported for monitoring only: a stopped worker must not take the API down with it.
    age = worker_heartbeat_age_seconds() if queue_ok else None
    body["worker"] = "unknown" if age is None else ("ok" if age <= max(settings.worker_heartbeat_seconds, 10) * 3 else "stale")
    if not queue_ok and settings.is_production_like:
        logger.warning("queue readiness check failed: redis_unreachable")
        return JSONResponse(status_code=503, content={**body, "status": "not_ready", "error": "queue_unavailable"})
    # Spec v1.2, Section 8: on staging/production the API must not run as a database user that
    # skips row-level security (a superuser, or the owner of the tables).
    if body["row_level_security"] == "bypassed" and settings.is_production_like:
        logger.error("database user bypasses row-level security; use the APP_DB_USER login")
        return JSONResponse(status_code=503, content={**body, "status": "not_ready", "error": "row_level_security_bypassed"})
    return body


def row_level_security_status(db) -> str:
    if db.get_bind().dialect.name != "postgresql":
        return "not_applicable"
    role = db.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar()
    owned = db.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user")).scalar()
    return "bypassed" if role or owned else "enforced"

@app.get("/features")
def features():
    return public_features()

# Switched-off channels and broadcasts answer 404 (spec v1.2, Section 2.1).
channel_scope = [Depends(require_channel_route_enabled)]
app.include_router(routes_auth.router)
app.include_router(routes_onboarding.router)
app.include_router(routes_channels.router, dependencies=channel_scope)
app.include_router(routes_dashboard.router)
app.include_router(routes_broadcasts.router, dependencies=[Depends(require_broadcasts_enabled)])
app.include_router(routes_webhook.router, dependencies=channel_scope)
app.include_router(routes_config.router)
app.include_router(routes_operations.router)
app.include_router(routes_runtime.router)
app.include_router(routes_uat.router)
app.include_router(routes_deployment.router)
app.include_router(routes_imports.router)
app.include_router(routes_team.router)
app.include_router(routes_widget.router)

app.include_router(routes_acceptance.router)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
