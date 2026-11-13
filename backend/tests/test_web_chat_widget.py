import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from app.api import routes_channels, routes_widget
from app.api.routes_operations import ConversationReplyRequest, reply_to_conversation
from app.api.routes_webhook import WebChatMessageRequest, receive_web_chat_message
from app.core.db import get_db
from app.models.entities import Base, ChannelConfig, Tenant
from app.schemas.channels import ChannelConfigRequest
from app.services import web_chat_widget as widget_service

VISITOR = "wv" + "A1b2C3d4" * 5
OTHER_VISITOR = "wv" + "Z9y8X7w6" * 5


class FakeRequest:
    def __init__(self, *, host: str = "127.0.0.1", headers: dict | None = None):
        self.client = SimpleNamespace(host=host)
        self.headers = headers or {}


def admin_ctx():
    return {"user": SimpleNamespace(id=77)}


def enable_web_chat(db, tenant, *, enabled: bool = True):
    row = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "web_chat").first()
    if not row:
        row = ChannelConfig(tenant_id=tenant.id, channel_type="web_chat", public_config_json={})
        db.add(row)
    row.status = "configured" if enabled else "not_connected"
    row.public_config_json = {**(row.public_config_json or {}), "enabled": enabled}
    db.commit()
    return row


def save_widget(db, tenant, **values):
    return routes_widget.save_widget_settings(routes_widget.WidgetSettingsRequest(**values), db=db, tenant=tenant, ctx=admin_ctx())


def frame(db, tenant, *, hl=None, accept_language=None):
    headers = {"accept-language": accept_language} if accept_language else {}
    return routes_widget.widget_frame(tenant.slug, FakeRequest(headers=headers), hl=hl, db=db)


def history(db, tenant, visitor_id=VISITOR, after=0):
    return routes_widget.web_chat_messages(tenant.slug, FakeRequest(), visitor_id=visitor_id, after=after, db=db)


def visitor_says(db, tenant, text, visitor_id=VISITOR):
    return receive_web_chat_message(tenant.slug, WebChatMessageRequest(visitor_id=visitor_id, message=text), FakeRequest(), db=db)


def test_website_addresses_are_normalized_and_unsafe_entries_refused():
    assert widget_service.normalize_websites(
        ["clinic.com", "https://www.clinic.com/contact?x=1", "HTTPS://WWW.CLINIC.COM/", "https://*.clinic.com", "http://localhost:3000", "  "]
    ) == ["https://clinic.com", "https://www.clinic.com", "https://*.clinic.com", "http://localhost:3000"]

    for unsafe in [
        "https://clinic.com; script-src *",
        "javascript:alert(1)",
        "https://user:pw@clinic.com",
        "https://clinic .com",
        "'self'",
        "*",
        "https://*.localhost",
        "ftp://clinic.com",
        "https://clinic.com:99999",
    ]:
        with pytest.raises(widget_service.InvalidWebsiteError):
            widget_service.normalize_website(unsafe)


def test_widget_settings_are_validated_saved_and_kept_by_the_channel_form(db, tenant):
    enable_web_chat(db, tenant)

    with pytest.raises(HTTPException) as exc:
        save_widget(db, tenant, allowed_websites=["https://clinic.com; frame-ancestors *"])
    assert exc.value.status_code == 400
    assert "is not a website address" in exc.value.detail

    saved = save_widget(db, tenant, allowed_websites=["www.clinic.com"], welcome_en="Welcome to the clinic!", language="en", position="left")
    assert saved["settings"] == {
        "allowed_websites": ["https://www.clinic.com"],
        "welcome_ar": "",
        "welcome_en": "Welcome to the clinic!",
        "language": "en",
        "position": "left",
    }
    assert saved["status"] == {"channel_enabled": True, "workspace_published": True, "has_websites": True}

    # Saving the general channel form (enable / live replies) must not erase the widget settings.
    routes_channels.update("web_chat", ChannelConfigRequest(status="configured", public_config={"enabled": True, "live_send_enabled": False}), db=db, tenant=tenant, _={})
    again = routes_widget.get_widget_settings(db=db, tenant=tenant, _={})
    assert again["settings"]["allowed_websites"] == ["https://www.clinic.com"]


def test_frame_may_only_be_shown_by_listed_websites_and_escapes_settings(db, tenant):
    enable_web_chat(db, tenant)
    save_widget(db, tenant, allowed_websites=["https://www.clinic.com"], welcome_en="Hi </script><script>alert(1)</script>")

    response = frame(db, tenant, hl="en")
    body = response.body.decode()
    csp = response.headers["Content-Security-Policy"]

    assert response.status_code == 200
    assert re.search(r"frame-ancestors 'self'( \S+)* https://www\.clinic\.com", csp)
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert "</script><script>alert(1)" not in body
    assert "\\u003c/script\\u003e" in body
    assert 'lang="en" dir="ltr"' in body


def test_frame_language_follows_setting_then_website_then_workspace(db, tenant):
    enable_web_chat(db, tenant)

    assert 'lang="ar" dir="rtl"' in frame(db, tenant).body.decode()  # workspace default
    assert 'lang="en" dir="ltr"' in frame(db, tenant, accept_language="en-GB,en;q=0.9").body.decode()
    assert 'lang="ar" dir="rtl"' in frame(db, tenant, hl="ar", accept_language="en-GB").body.decode()

    save_widget(db, tenant, language="en")
    assert 'lang="en" dir="ltr"' in frame(db, tenant, hl="ar").body.decode()


def test_frame_is_unavailable_when_chat_is_off_or_workspace_unpublished(db, tenant):
    enable_web_chat(db, tenant, enabled=False)
    off = frame(db, tenant)
    assert off.status_code == 404
    assert "frame-ancestors 'none'" in off.headers["Content-Security-Policy"]

    enable_web_chat(db, tenant)
    tenant.status = "draft"
    db.commit()
    assert frame(db, tenant).status_code == 404
    assert routes_widget.widget_preview(tenant.slug, db=db).status_code == 404


def test_visitor_reads_own_chat_including_staff_replies_and_nobody_else_does(db, tenant):
    enable_web_chat(db, tenant)

    first = visitor_says(db, tenant, "what is the price?")
    page = history(db, tenant)
    assert [(m["from"], m["text"]) for m in page["messages"]] == [
        ("visitor", "what is the price?"),
        ("agent", "The course costs 1500 SAR and lasts one month."),
    ]
    assert page["state"] == "BOT_ACTIVE"
    last_id = page["messages"][-1]["id"]

    handoff = visitor_says(db, tenant, "Can I speak to someone please?")
    assert handoff["handoff"] is True
    reply_to_conversation(int(first["conversation_id"]), ConversationReplyRequest(text="Hi, this is Sara from the front desk."), tenant=tenant, db=db, ctx=admin_ctx())

    newer = history(db, tenant, after=last_id)
    assert [m["from"] for m in newer["messages"]] == ["visitor", "agent", "team"]
    assert newer["messages"][-1]["text"] == "Hi, this is Sara from the front desk."
    assert newer["state"] == "HUMAN_HANDOFF"
    assert set(newer["messages"][0]) == {"id", "from", "text", "created_at"}

    assert history(db, tenant, visitor_id=OTHER_VISITOR) == {"messages": [], "state": None}


def test_history_needs_a_long_random_visitor_id_and_matches_stored_form(db, tenant):
    enable_web_chat(db, tenant)

    with pytest.raises(HTTPException) as exc:
        history(db, tenant, visitor_id="visitor-123")
    assert exc.value.status_code == 400

    # The message endpoint trims trailing separators; history must find the same visitor.
    trailing = VISITOR + "-"
    visitor_says(db, tenant, "hello", visitor_id=trailing)
    assert len(history(db, tenant, visitor_id=trailing)["messages"]) == 2


def test_history_is_refused_when_chat_is_off(db, tenant):
    enable_web_chat(db, tenant, enabled=False)
    with pytest.raises(HTTPException) as exc:
        history(db, tenant)
    assert exc.value.status_code == 403


@pytest.fixture()
def api_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        tenant = Tenant(slug="web-tenant", display_name="Web Tenant", default_lang="en", status="active")
        session.add(tenant)
        session.flush()
        session.add(ChannelConfig(
            tenant_id=tenant.id,
            channel_type="web_chat",
            status="configured",
            public_config_json={"enabled": True, "widget": {"allowed_websites": ["https://www.clinic.com"]}},
        ))
        session.commit()

    def override_db():
        with Session() as session:
            yield session

    main.app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_db, None)


def test_only_the_chat_frame_can_be_embedded_and_assets_are_served(api_client):
    page = api_client.get("/widget/web-tenant/frame")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "X-Frame-Options" not in page.headers
    assert "https://www.clinic.com" in page.headers["Content-Security-Policy"]

    assert api_client.get("/health").headers["X-Frame-Options"] == "DENY"

    loader = api_client.get("/widget.js")
    assert loader.status_code == 200
    assert loader.headers["content-type"].startswith("application/javascript")
    assert loader.headers["cache-control"] == "public, max-age=300"

    for asset in re.findall(r'"\.\./assets/([a-z.]+)\?v=[0-9a-f]+"', page.text):
        assert api_client.get(f"/widget/assets/{asset}").status_code == 200
    assert len(re.findall(r'\.\./assets/', page.text)) == 2
    assert api_client.get("/widget/assets/loader.js").status_code == 404

    preview = api_client.get("/widget/web-tenant/preview")
    assert preview.status_code == 200
    assert 'src="../../widget.js" data-workspace="web-tenant"' in preview.text
