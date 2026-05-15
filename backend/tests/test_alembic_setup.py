from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.entities import Base


def test_alembic_has_one_head_and_metadata_loads():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20260515_0002"]
    assert len(Base.metadata.tables) == 20
    assert "tenants" in Base.metadata.tables
    assert "webhook_events" in Base.metadata.tables


def test_baseline_revision_imports_successfully():
    backend_dir = Path(__file__).resolve().parents[1]
    revision_path = backend_dir / "migrations" / "versions" / "20260515_0001_baseline.py"
    spec = spec_from_file_location("baseline_revision", revision_path)
    assert spec is not None
    assert spec.loader is not None

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260515_0001"
    assert module.down_revision is None
    assert callable(module.upgrade)


def test_performance_index_revision_follows_baseline_and_names_expected_indexes():
    backend_dir = Path(__file__).resolve().parents[1]
    revision_path = backend_dir / "migrations" / "versions" / "20260515_0002_performance_indexes.py"
    spec = spec_from_file_location("performance_index_revision", revision_path)
    assert spec is not None
    assert spec.loader is not None

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260515_0002"
    assert module.down_revision == "20260515_0001"
    index_names = {name for name, _table_name, _columns in module.INDEXES}
    assert index_names == {
        "ix_conversations_tenant_state_updated_at",
        "ix_conversations_tenant_updated_at",
        "ix_messages_tenant_conversation_created_at",
        "ix_tickets_tenant_status_created_at",
        "ix_tickets_tenant_priority_status",
        "ix_broadcasts_tenant_status_schedule_at",
        "ix_broadcasts_tenant_created_by",
        "ix_broadcast_recipients_tenant_broadcast_status",
        "ix_broadcast_recipients_tenant_customer_id",
        "ix_webhook_events_tenant_provider_event_id",
        "ix_webhook_events_provider_event_type_created_at",
        "ix_channel_configs_channel_type_status",
        "ix_channel_configs_tenant_channel_status",
        "ix_audit_logs_tenant_created_at",
        "ix_audit_logs_tenant_actor_created_at",
        "ix_audit_logs_tenant_entity",
        "ix_customers_tenant_created_at",
        "ix_faq_items_tenant_status",
        "ix_intent_keywords_tenant_intent_code",
    }
