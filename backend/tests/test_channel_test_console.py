import pytest
from fastapi import HTTPException

from app.api import routes_dashboard
from app.api import routes_channels
from app.core.security import hash_password
from app.core.tenancy import ROLE_BUSINESS_ADMIN, require_tenant_roles
from app.models.entities import ChannelConfig, Conversation, Customer, Message, Tenant, TenantUserRole, User
from app.schemas.channels import ChannelTestConsoleRequest
from app.services.tenant_channel_service import TenantChannelService


def create_admin(db, tenant):
    user = User(email="console-admin@example.com", full_name="Console Admin", password_hash=hash_password("Secret123!"))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.commit()
    return user


def enable_channel(db, tenant, channel_type: str, *, enabled: bool = True, status: str = "configured"):
    svc = TenantChannelService()
    row = (
        db.query(ChannelConfig)
        .filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == channel_type)
        .first()
    )
    if not row:
        row = ChannelConfig(tenant_id=tenant.id, channel_type=channel_type)
        db.add(row)
    row.status = status
    row.public_config_json = {"enabled": enabled, "live_send_enabled": True}
    row.encrypted_credentials = svc.encrypt_credentials(
        {
            "bot_token": "telegram-token",
            "access_token": "whatsapp-token",
            "phone_number_id": "phone-test",
            "smtp_host": "smtp.example.test",
            "smtp_port": "587",
            "smtp_username": "smtp-user",
            "smtp_password": "smtp-password",
            "smtp_from_email": "support@example.test",
            "page_access_token": "meta-token",
            "page_id": "page-test",
            "instagram_business_account_id": "ig-test",
        }
    )
    db.commit()
    return row


def test_channel_test_console_enabled_channel_returns_reply_and_synthetic_identity(db, tenant):
    create_admin(db, tenant)
    enable_channel(db, tenant, "telegram")

    result = routes_channels.test_console_message(
        ChannelTestConsoleRequest(channel_type="telegram", session_id="session-one", message="what is the price?"),
        db=db,
        tenant=tenant,
        _={},
    ).model_dump()

    assert result["reply"] == "The course costs 1500 SAR and lasts one month."
    assert result["channel_type"] == "telegram"
    assert result["session_id"] == "session-one"
    assert result["handoff"] is False
    assert result["intent"] == "PRICING"
    assert result["conversation_id"] == f"virtual:{tenant.id}:telegram:session-one"
    assert result["notes"] == ["Virtual test only. No inbox conversation, customer, message, or provider send was created."]
    assert "telegram-token" not in str(result)
    assert db.query(Customer).filter(Customer.tenant_id == tenant.id).count() == 0
    assert db.query(Conversation).filter(Conversation.tenant_id == tenant.id).count() == 0
    assert db.query(Message).filter(Message.tenant_id == tenant.id).count() == 0


def test_channel_test_console_disabled_channel_is_rejected(db, tenant):
    enable_channel(db, tenant, "web_chat", enabled=False)

    with pytest.raises(HTTPException) as exc:
        routes_channels.test_console_message(
            ChannelTestConsoleRequest(channel_type="web_chat", session_id="session-one", message="hello"),
            db=db,
            tenant=tenant,
            _={},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "channel_disabled"


def test_channel_test_console_unimplemented_channel_is_rejected(db, tenant):
    with pytest.raises(HTTPException) as exc:
        routes_channels.test_console_message(
            ChannelTestConsoleRequest(channel_type="sms", session_id="session-one", message="hello"),
            db=db,
            tenant=tenant,
            _={},
        )

    assert exc.value.status_code == 400


def test_channel_test_console_tenant_mismatch_is_rejected_by_tenant_dependency(db, tenant):
    admin = create_admin(db, tenant)
    other = Tenant(slug="other-console", display_name="Other", timezone="Asia/Riyadh", default_lang="en", status="active")
    db.add(other)
    db.commit()
    role_check = require_tenant_roles(ROLE_BUSINESS_ADMIN)

    with pytest.raises(HTTPException) as exc:
        role_check(db=db, user=admin, tenant=other)

    assert exc.value.status_code == 403


def test_channel_test_console_synthetic_identity_is_tenant_scoped(db, tenant):
    enable_channel(db, tenant, "web_chat")
    other = Tenant(slug="other-console-identity", display_name="Other", timezone="Asia/Riyadh", default_lang="en", status="active")
    db.add(other)
    db.flush()
    enable_channel(db, other, "web_chat")

    first = routes_channels.test_console_message(
        ChannelTestConsoleRequest(channel_type="web_chat", session_id="same-session", message="hello"),
        db=db,
        tenant=tenant,
        _={},
    )
    second = routes_channels.test_console_message(
        ChannelTestConsoleRequest(channel_type="web_chat", session_id="same-session", message="hello"),
        db=db,
        tenant=other,
        _={},
    )

    assert first.conversation_id != second.conversation_id
    assert first.conversation_id == f"virtual:{tenant.id}:web_chat:same-session"
    assert second.conversation_id == f"virtual:{other.id}:web_chat:same-session"
    assert db.query(Customer).filter(Customer.phone.like("webchat:test:%:web_chat:same-session")).count() == 0
    assert db.query(Conversation).count() == 0
    assert db.query(Message).count() == 0


def test_channel_test_console_does_not_call_real_provider_sends(db, tenant, monkeypatch):
    for channel_type in ["telegram", "whatsapp", "email", "instagram", "facebook"]:
        enable_channel(db, tenant, channel_type)

    def explode(*args, **kwargs):
        raise AssertionError("provider send should not be called")

    monkeypatch.setattr("app.services.telegram_adapter.TelegramAdapter.send_text", explode)
    monkeypatch.setattr("app.services.whatsapp_adapter.WhatsAppAdapter.send_text", explode)
    monkeypatch.setattr("app.services.email_adapter.EmailAdapter.send_text", explode)
    monkeypatch.setattr("app.services.meta_social_adapter.MetaSocialAdapter.send_text", explode)

    for channel_type in ["telegram", "whatsapp", "email", "instagram", "facebook"]:
        result = routes_channels.test_console_message(
            ChannelTestConsoleRequest(channel_type=channel_type, session_id=f"{channel_type}-dry", message="what is the price?"),
            db=db,
            tenant=tenant,
            _={},
        )
        assert result.reply


def test_channel_test_console_handoff_state_is_returned(db, tenant):
    enable_channel(db, tenant, "web_chat")

    result = routes_channels.test_console_message(
        ChannelTestConsoleRequest(channel_type="web_chat", session_id="handoff", message="human"),
        db=db,
        tenant=tenant,
        _={},
    )

    assert result.reply == "I've passed your request to our team. A team member will reply as soon as possible."
    assert result.handoff is True
    assert result.state == "HUMAN_HANDOFF"


def test_channel_test_console_hands_off_a_request_for_a_person_without_a_human_topic(db, tenant):
    from app.models.entities import IntentDefinition

    enable_channel(db, tenant, "web_chat")
    db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == "HUMAN_REQUEST").update({"enabled": False})
    db.commit()

    result = routes_channels.test_console_message(
        ChannelTestConsoleRequest(channel_type="web_chat", session_id="person", message="Can I talk to a person please?"),
        db=db,
        tenant=tenant,
        _={},
    )

    assert result.intent == "HUMAN_REQUEST"
    assert result.handoff is True
    assert result.state == "HUMAN_HANDOFF"


def test_channel_test_console_clarifies_in_the_customer_language(db, tenant):
    enable_channel(db, tenant, "web_chat")

    english = routes_channels.test_console_message(
        ChannelTestConsoleRequest(channel_type="web_chat", session_id="clarify-en", message="do you accept medical insurance today"),
        db=db,
        tenant=tenant,
        _={},
    )
    no_language = routes_channels.test_console_message(
        ChannelTestConsoleRequest(channel_type="web_chat", session_id="clarify-default", message="777 ؟؟"),
        db=db,
        tenant=tenant,
        _={},
    )

    assert english.state == "CLARIFYING"
    assert english.reply == "Could you clarify your request?"
    assert no_language.state == "CLARIFYING"
    assert no_language.reply == "ممكن توضح طلبك أكثر؟"


def test_legacy_test_console_conversations_are_hidden_from_dashboard(db, tenant):
    real_customer = Customer(tenant_id=tenant.id, phone="0500000099", name="Real Customer")
    synthetic_customer = Customer(
        tenant_id=tenant.id,
        phone=f"tg:test:{tenant.id}:telegram:test_legacy-session",
        tags_json=[
            "channel:telegram",
            f"telegram_chat_id:test:{tenant.id}:telegram:test_legacy-session",
        ],
    )
    db.add_all([real_customer, synthetic_customer])
    db.flush()

    real_conversation = Conversation(
        tenant_id=tenant.id,
        customer_id=real_customer.id,
        channel_type="whatsapp",
        state="BOT_ACTIVE",
        owner_type="BOT",
        owner_ref="BOT",
    )
    synthetic_conversation = Conversation(
        tenant_id=tenant.id,
        customer_id=synthetic_customer.id,
        channel_type="telegram",
        state="BOT_ACTIVE",
        owner_type="BOT",
        owner_ref="BOT",
    )
    db.add_all([real_conversation, synthetic_conversation])
    db.flush()
    db.add_all(
        [
            Message(tenant_id=tenant.id, conversation_id=real_conversation.id, direction="inbound", text="hello"),
            Message(tenant_id=tenant.id, conversation_id=synthetic_conversation.id, direction="inbound", text="fake test hello"),
        ]
    )
    db.commit()

    inbox_rows = routes_dashboard.inbox(state=None, owner_ref=None, db=db, tenant=tenant, _={})
    customer_rows = routes_dashboard.customers(search=None, db=db, tenant=tenant, _={})

    assert [row["id"] for row in inbox_rows] == [real_conversation.id]
    assert [row["id"] for row in customer_rows] == [real_customer.id]
    with pytest.raises(HTTPException) as exc:
        routes_dashboard.detail(conversation_id=synthetic_conversation.id, db=db, tenant=tenant, _={})
    assert exc.value.status_code == 404
