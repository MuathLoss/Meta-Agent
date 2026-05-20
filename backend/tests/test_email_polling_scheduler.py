from contextlib import nullcontext

from app.models.entities import ChannelConfig, Tenant
from app.services.email_polling_scheduler import EmailPollingScheduler
from app.services.email_polling_service import EmailPollResult
from app.services.tenant_channel_service import TenantChannelService


def add_email_channel(
    db,
    tenant,
    *,
    enabled: bool = True,
    live_send_enabled: bool = True,
    credentials: dict | None = None,
    status: str = "configured",
):
    svc = TenantChannelService()
    row = ChannelConfig(
        tenant_id=tenant.id,
        channel_type="email",
        status=status,
        public_config_json={"enabled": enabled, "live_send_enabled": live_send_enabled},
        encrypted_credentials=svc.encrypt_credentials(credentials or {}) if credentials is not None else None,
    )
    db.add(row)
    db.commit()
    return row


def imap_credentials(**extra):
    return {
        "imap_host": "imap.example.test",
        "imap_port": "993",
        "imap_username": "tenant-inbox",
        "imap_password": "tenant-imap-password",
        **extra,
    }


class FakePollingService:
    def __init__(self, *, fail_tenant_id: int | None = None):
        self.fail_tenant_id = fail_tenant_id
        self.polled: list[int] = []

    def poll_channel(self, db, row):
        self.polled.append(row.tenant_id)
        if row.tenant_id == self.fail_tenant_id:
            raise TimeoutError("imap timed out with tenant-imap-password")
        return EmailPollResult(
            tenant_id=row.tenant_id,
            channel_id=row.id,
            messages_seen=2,
            messages_processed=1,
        )


def scheduler_for(db, polling_service):
    return EmailPollingScheduler(session_factory=lambda: nullcontext(db), polling_service=polling_service)


def test_email_scheduler_skips_disabled_channel(db, tenant):
    add_email_channel(db, tenant, enabled=False, live_send_enabled=True, credentials=imap_credentials())
    fake = FakePollingService()

    summary = scheduler_for(db, fake).run_once()

    assert summary.channels_seen == 1
    assert summary.channels_skipped == 1
    assert summary.channels_polled == 0
    assert fake.polled == []


def test_email_scheduler_skips_missing_imap_credentials(db, tenant):
    add_email_channel(db, tenant, enabled=True, live_send_enabled=True, credentials={"imap_host": "imap.example.test"})
    fake = FakePollingService()

    summary = scheduler_for(db, fake).run_once()

    assert summary.channels_seen == 1
    assert summary.channels_skipped == 1
    assert summary.channels_polled == 0
    assert fake.polled == []


def test_email_scheduler_polls_enabled_ready_email_channel(db, tenant):
    add_email_channel(db, tenant, enabled=True, live_send_enabled=True, credentials=imap_credentials())
    fake = FakePollingService()

    summary = scheduler_for(db, fake).run_once()

    assert summary.channels_seen == 1
    assert summary.channels_skipped == 0
    assert summary.channels_polled == 1
    assert summary.messages_seen == 2
    assert summary.messages_processed == 1
    assert fake.polled == [tenant.id]


def test_email_scheduler_one_tenant_failure_does_not_stop_other_tenant(db, tenant):
    add_email_channel(db, tenant, enabled=True, live_send_enabled=True, credentials=imap_credentials())
    other = Tenant(slug="other-email-scheduler", display_name="Other", timezone="Asia/Riyadh", default_lang="en", status="active")
    db.add(other)
    db.flush()
    add_email_channel(db, other, enabled=True, live_send_enabled=True, credentials=imap_credentials(imap_username="other-inbox"))
    fake = FakePollingService(fail_tenant_id=tenant.id)

    summary = scheduler_for(db, fake).run_once()

    assert summary.channels_seen == 2
    assert summary.channels_polled == 1
    assert summary.errors == 1
    assert fake.polled == [tenant.id, other.id]


def test_email_scheduler_summary_and_logs_do_not_expose_secrets(db, tenant, caplog):
    add_email_channel(db, tenant, enabled=True, live_send_enabled=True, credentials=imap_credentials())
    fake = FakePollingService(fail_tenant_id=tenant.id)

    summary = scheduler_for(db, fake).run_once()

    assert summary.errors == 1
    assert "tenant-imap-password" not in str(summary)
    assert "tenant-imap-password" not in caplog.text
