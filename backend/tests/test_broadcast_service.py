from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.entities import Broadcast, BroadcastRecipient, ChannelConfig, Customer, Message
from app.services.broadcast_service import BroadcastService
from app.services.outbound_service import OutboundService
from app.services.tenant_channel_service import TenantChannelService


def _enable_live_whatsapp(db, tenant):
    svc = TenantChannelService()
    channel = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant.id, ChannelConfig.channel_type == "whatsapp").first()
    channel.status = "connected"
    channel.public_config_json = {"enabled": True, "live_send_enabled": True, "phone_number_id": "phone-test"}
    channel.encrypted_credentials = svc.encrypt_credentials({
        "verify_token": "verify-test",
        "app_secret": "secret-test",
        "phone_number_id": "phone-test",
        "access_token": "live-token",
    })
    db.flush()


def _fake_send_or_store(self, db, *, tenant_id, conversation_id, channel_type, destination, text, intent_code):
    row = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        provider_message_id=f"{channel_type}-message-{destination}-{uuid4()}",
        text=text,
        payload_json={"send_status": "sent", "channel_type": channel_type, "destination": destination},
        intent_code=intent_code,
    )
    db.add(row)
    db.flush()
    return row


def test_broadcast_send_can_be_repeated_for_same_campaign(db, tenant, monkeypatch):
    _enable_live_whatsapp(db, tenant)
    monkeypatch.setattr(OutboundService, "send_or_store", _fake_send_or_store)
    c1 = Customer(tenant_id=tenant.id, phone="0501", opt_in=True)
    c2 = Customer(tenant_id=tenant.id, phone="0502", opt_in=False)
    db.add_all([c1, c2])
    db.flush()
    b = Broadcast(tenant_id=tenant.id, title="Test", channel_type="whatsapp", audience_type="all", status="draft", payload_json={})
    db.add(b)
    db.flush()
    svc = BroadcastService()
    r1 = svc.send_now(db, tenant=tenant, broadcast=b)
    r2 = svc.send_now(db, tenant=tenant, broadcast=b)
    assert r1.created_recipients == 1
    assert r2.created_recipients == 1
    assert b.status == "sent"
    tracked = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == b.id).all()
    assert len(tracked) == 2


def test_due_broadcasts_are_processed(db, tenant, monkeypatch):
    _enable_live_whatsapp(db, tenant)
    monkeypatch.setattr(OutboundService, "send_or_store", _fake_send_or_store)
    db.add(Customer(tenant_id=tenant.id, phone="0503", opt_in=True))
    due = Broadcast(tenant_id=tenant.id, title="Due", channel_type="whatsapp", audience_type="all", status="scheduled", schedule_at=datetime.now(timezone.utc) - timedelta(minutes=1), payload_json={})
    future = Broadcast(tenant_id=tenant.id, title="Future", channel_type="whatsapp", audience_type="all", status="scheduled", schedule_at=datetime.now(timezone.utc) + timedelta(days=1), payload_json={})
    db.add_all([due, future])
    db.flush()
    results = BroadcastService().process_due_broadcasts(db)
    assert len(results) == 1
    assert due.status == "sent"
    assert future.status == "scheduled"


def test_broadcast_send_uses_connected_runtime_channel_and_tracks_delivery(db, tenant, monkeypatch):
    svc = TenantChannelService()
    db.add(ChannelConfig(
        tenant_id=tenant.id,
        channel_type="telegram",
        status="connected",
        public_config_json={"enabled": True, "live_send_enabled": True},
        encrypted_credentials=svc.encrypt_credentials({"bot_token": "telegram-test-token"}),
    ))
    customer = Customer(tenant_id=tenant.id, phone="123456789", opt_in=True)
    db.add(customer)
    db.flush()
    broadcast = Broadcast(
        tenant_id=tenant.id,
        title="Triplet Promo",
        channel_type="auto",
        audience_type="all",
        status="draft",
        payload_json={"message_text": "Hello from broadcast"},
    )
    db.add(broadcast)
    db.flush()

    def fake_send_or_store(db, *, tenant_id, conversation_id, channel_type, destination, text, intent_code):
        row = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            provider_message_id="telegram-message-1",
            text=text,
            payload_json={"send_status": "sent", "channel_type": channel_type, "destination": destination},
            intent_code=intent_code,
        )
        db.add(row)
        db.flush()
        return row

    service = BroadcastService()
    monkeypatch.setattr(service.outbound_service, "send_or_store", fake_send_or_store)

    result = service.send_now(db, tenant=tenant, broadcast=broadcast)

    recipient = db.query(Message).filter(Message.provider_message_id == "telegram-message-1").first()
    assert result.status == "sent"
    assert result.channel_type == "telegram"
    assert result.sent_recipients == 1
    assert result.failed_recipients == 0
    assert recipient is not None
    tracked = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).all()
    assert len(tracked) == 1
    assert tracked[0].status == "sent"


def test_telegram_unreachable_recipients_are_marked_and_skipped_later(db, tenant, monkeypatch):
    svc = TenantChannelService()
    db.add(ChannelConfig(
        tenant_id=tenant.id,
        channel_type="telegram",
        status="connected",
        public_config_json={"enabled": True, "live_send_enabled": True},
        encrypted_credentials=svc.encrypt_credentials({"bot_token": "telegram-test-token"}),
    ))
    blocked = Customer(tenant_id=tenant.id, phone="tg:111", opt_in=True, tags_json=["telegram_chat_id:111", "telegram_reachable:true"])
    healthy = Customer(tenant_id=tenant.id, phone="tg:222", opt_in=True, tags_json=["telegram_chat_id:222", "telegram_reachable:true"])
    db.add_all([blocked, healthy])
    db.flush()
    broadcast = Broadcast(
        tenant_id=tenant.id,
        title="Telegram Promo",
        channel_type="telegram",
        audience_type="all",
        status="draft",
        payload_json={"message_text": "hello"},
    )
    db.add(broadcast)
    db.flush()

    def fake_send_or_store(self, db, *, tenant_id, conversation_id, channel_type, destination, text, intent_code):
        if destination == "111":
            row = Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                direction="outbound",
                provider_message_id=f"local-{uuid4()}",
                text=text,
                payload_json={"send_status": "send_failed", "channel_type": channel_type, "destination": destination, "error": "403 Forbidden: bot was blocked by the user"},
                intent_code=intent_code,
            )
        else:
            row = Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                direction="outbound",
                provider_message_id=f"telegram-message-{uuid4()}",
                text=text,
                payload_json={"send_status": "sent", "channel_type": channel_type, "destination": destination},
                intent_code=intent_code,
            )
        db.add(row)
        db.flush()
        return row

    service = BroadcastService()
    monkeypatch.setattr(service.outbound_service, "send_or_store", fake_send_or_store.__get__(service.outbound_service, type(service.outbound_service)))

    first = service.send_now(db, tenant=tenant, broadcast=broadcast)
    db.flush()
    db.refresh(blocked)
    second = service.send_now(db, tenant=tenant, broadcast=broadcast)

    assert first.failed_recipients == 1
    assert first.sent_recipients == 1
    assert "telegram_reachable:false" in (blocked.tags_json or [])
    assert second.total_recipients == 1
    assert second.sent_recipients == 1
