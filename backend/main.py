from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import routes_auth, routes_onboarding, routes_channels, routes_dashboard, routes_broadcasts, routes_webhook, routes_config, routes_operations, routes_runtime, routes_uat, routes_deployment, routes_acceptance
from app.core.config import settings
from app.core.db import SessionLocal

app = FastAPI(title="Configurable Multi-Tenant Business Agent Platform", version="0.7.0")
uploads_dir = Path(__file__).resolve().parent / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.app_env, "app": "business-agent-platform"}

@app.get("/health/ready")
def readiness():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        return {"status": "not_ready", "database": "error", "detail": str(exc)}

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

app.include_router(routes_acceptance.router)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
