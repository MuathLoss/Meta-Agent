"""Website chat widget routes.

Public (no sign-in, used on institutions' websites):
  GET /widget.js                              the script institutions paste into their site
  GET /widget/assets/{name}                   the chat frame's script and styles
  GET /widget/{slug}/frame                    the chat itself, shown inside the website
  GET /widget/{slug}/preview                  a sample page to try the widget
  GET /channels/web-chat/{slug}/messages      a visitor's own messages, including staff replies

Workspace admins:
  GET/PUT /channels/web_chat/widget           widget settings
"""
from __future__ import annotations

import html
import re
from hashlib import sha256
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes_config import audit
from app.core.db import get_db
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import Tenant
from app.services import web_chat_widget as widget_service
from app.services.customer_channel_identity_service import CustomerChannelIdentityService
from app.services.tenant_channel_service import TenantChannelService, UnsafePublicConfigError
from app.services.web_chat_adapter import WebChatAdapter

router = APIRouter(tags=["web-chat-widget"])
channel_service = TenantChannelService()
customer_identity = CustomerChannelIdentityService()
web_chat_adapter = WebChatAdapter()

ASSET_DIR = Path(__file__).resolve().parents[1] / "widget"
ASSET_TYPES = {
    "frame.js": "application/javascript; charset=utf-8",
    "frame.css": "text/css; charset=utf-8",
    "preview.css": "text/css; charset=utf-8",
}
ASSET_VERSIONS = {name: sha256((ASSET_DIR / name).read_bytes()).hexdigest()[:12] for name in ASSET_TYPES}
LOADER_CACHE = "public, max-age=300"
ASSET_CACHE = "public, max-age=86400"
HISTORY_LIMIT_PER_VISITOR = 40
HISTORY_LIMIT_PER_ADDRESS = 600
RATE_WINDOW_SECONDS = 60
PLACEHOLDER_RE = re.compile(r"__([A-Z_]+?)__")


def _asset_url(name: str) -> str:
    # Relative to /widget/{slug}/frame and /widget/{slug}/preview, so it works with or
    # without a path prefix in front of the backend (for example /api behind the proxy).
    return f"../assets/{name}?v={ASSET_VERSIONS[name]}"


def _fill(template: str, **values: str) -> str:
    # One pass, so text inserted for one placeholder is never treated as another placeholder.
    page = (ASSET_DIR / template).read_text(encoding="utf-8")
    return PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], page)


def _not_available() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>Chat unavailable</title>",
        status_code=404,
        headers={"Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"},
    )


def _active_tenant(db: Session, slug: str) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.slug == slug, Tenant.status == "active").first()


@router.get("/widget.js")
def widget_loader() -> Response:
    return Response(
        (ASSET_DIR / "loader.js").read_bytes(),
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": LOADER_CACHE},
    )


@router.get("/widget/assets/{name}")
def widget_asset(name: str) -> Response:
    if name not in ASSET_TYPES:
        raise HTTPException(status_code=404, detail="Not found")
    return Response((ASSET_DIR / name).read_bytes(), media_type=ASSET_TYPES[name], headers={"Cache-Control": ASSET_CACHE})


@router.get("/widget/{tenant_slug}/frame")
def widget_frame(tenant_slug: str, request: Request, hl: str | None = Query(default=None, max_length=12), db: Session = Depends(get_db)) -> HTMLResponse:
    tenant = _active_tenant(db, tenant_slug)
    channel = widget_service.web_chat_channel(db, tenant.id) if tenant else None
    if not tenant or not widget_service.channel_enabled(channel):
        return _not_available()
    widget = widget_service.read_settings(channel)
    lang = widget_service.resolve_language(widget, tenant, host_lang=hl, accept_language=request.headers.get("accept-language"))
    config = widget_service.frame_config(db, tenant, widget, lang=lang)
    page = _fill(
        "frame.html",
        LANG=lang,
        DIR=config["dir"],
        TITLE=html.escape(config["title"]),
        CSS_URL=_asset_url("frame.css"),
        JS_URL=_asset_url("frame.js"),
        CONFIG_JSON=widget_service.json_for_html(config),
    )
    return HTMLResponse(page, headers={"Content-Security-Policy": widget_service.frame_csp(widget)})


@router.get("/widget/{tenant_slug}/preview")
def widget_preview(tenant_slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    tenant = _active_tenant(db, tenant_slug)
    if not tenant or not widget_service.channel_enabled(widget_service.web_chat_channel(db, tenant.id)):
        return _not_available()
    page = _fill("preview.html", SLUG=html.escape(tenant.slug), TITLE=html.escape(tenant.display_name), CSS_URL=_asset_url("preview.css"))
    return HTMLResponse(page, headers={"Content-Security-Policy": widget_service.preview_csp()})


@router.get("/channels/web-chat/{tenant_slug}/messages")
def web_chat_messages(
    tenant_slug: str,
    request: Request,
    visitor_id: str = Query(min_length=1, max_length=128),
    after: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if not widget_service.HISTORY_VISITOR_ID_RE.match(visitor_id):
        raise HTTPException(status_code=400, detail="This chat session is not valid. Reload the page to start a new chat.")
    enforce_rate_limit(f"webchat:history:{tenant_slug}:{visitor_id}", max_requests=HISTORY_LIMIT_PER_VISITOR, window_seconds=RATE_WINDOW_SECONDS)
    enforce_rate_limit(f"webchat:history-ip:{tenant_slug}:{client_ip(request)}", max_requests=HISTORY_LIMIT_PER_ADDRESS, window_seconds=RATE_WINDOW_SECONDS)
    tenant = _active_tenant(db, tenant_slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not widget_service.channel_enabled(widget_service.web_chat_channel(db, tenant.id)):
        raise HTTPException(status_code=403, detail="Web chat is not enabled for this tenant")

    # Same address the message endpoint stores, so a visitor only ever reads their own chat.
    normalized_id = web_chat_adapter.normalize_visitor_id(visitor_id)
    customer = customer_identity.lookup_customer(db, tenant_id=tenant.id, channel_type="web_chat", address=f"{tenant.id}:{normalized_id}")
    if not customer:
        return {"messages": [], "state": None}
    messages, state = widget_service.visitor_history(db, tenant_id=tenant.id, customer_id=customer.id, after=after)
    return {"messages": messages, "state": state}


class WidgetSettingsRequest(BaseModel):
    allowed_websites: list[str] = Field(default_factory=list, max_length=50)
    welcome_ar: str = Field(default="", max_length=widget_service.MAX_WELCOME_LENGTH)
    welcome_en: str = Field(default="", max_length=widget_service.MAX_WELCOME_LENGTH)
    language: Literal["auto", "ar", "en"] = "auto"
    position: Literal["right", "left"] = "right"


def _settings_response(tenant: Tenant, channel) -> dict:
    widget = widget_service.read_settings(channel)
    return {
        "workspace": tenant.slug,
        "settings": widget.as_dict(),
        "status": {
            "channel_enabled": widget_service.channel_enabled(channel),
            "workspace_published": tenant.status == "active",
            "has_websites": bool(widget.allowed_websites),
        },
    }


@router.get("/channels/web_chat/widget")
def get_widget_settings(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    return _settings_response(tenant, widget_service.web_chat_channel(db, tenant.id))


@router.put("/channels/web_chat/widget")
def save_widget_settings(
    payload: WidgetSettingsRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    try:
        websites = widget_service.normalize_websites(payload.allowed_websites)
    except widget_service.InvalidWebsiteError as exc:
        raise HTTPException(
            status_code=400,
            detail=f'"{exc.value[:80]}" is not a website address. Enter addresses like https://www.example.com, one per line.',
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    widget = widget_service.WidgetSettings(
        allowed_websites=websites,
        welcome_ar=payload.welcome_ar.strip(),
        welcome_en=payload.welcome_en.strip(),
        language=payload.language,
        position=payload.position,
    )
    channel = widget_service.web_chat_channel(db, tenant.id)
    status = channel.status if channel else "not_connected"
    try:
        channel = channel_service.upsert(db, tenant.id, "web_chat", status, {"widget": widget.as_dict()}, {})
    except UnsafePublicConfigError as exc:
        raise HTTPException(status_code=400, detail="The welcome message looks like it contains a password or key. Remove it and try again.") from exc
    audit(db, tenant.id, ctx["user"].id, "channel.web_chat_widget.updated", "channel", "web_chat", {"allowed_websites": websites, "language": widget.language, "position": widget.position})
    db.commit()
    return _settings_response(tenant, channel)
