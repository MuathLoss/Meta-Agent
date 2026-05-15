from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.entities import Base


def test_alembic_has_one_head_and_metadata_loads():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20260515_0005"]
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


def test_nullability_cleanup_revision_follows_indexes_and_contains_expected_operations():
    backend_dir = Path(__file__).resolve().parents[1]
    revision_path = backend_dir / "migrations" / "versions" / "20260515_0003_nullability_drift_cleanup.py"
    source = revision_path.read_text()
    spec = spec_from_file_location("nullability_cleanup_revision", revision_path)
    assert spec is not None
    assert spec.loader is not None

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260515_0003"
    assert module.down_revision == "20260515_0002"
    assert "UPDATE intent_definitions SET supported_languages = 'ar' WHERE supported_languages IS NULL" in source
    assert "UPDATE intent_definitions SET response_mode = 'faq' WHERE response_mode IS NULL" in source
    assert "UPDATE conversations SET metadata_json = '{}' WHERE metadata_json IS NULL" in source
    assert source.count("nullable=False") == 3
    assert '"supported_languages"' in source
    assert '"response_mode"' in source
    assert '"metadata_json"' in source


def test_tenant_webhook_uniqueness_revision_follows_nullability_cleanup():
    backend_dir = Path(__file__).resolve().parents[1]
    revision_path = backend_dir / "migrations" / "versions" / "20260515_0004_tenant_webhook_uniqueness.py"
    source = revision_path.read_text()
    spec = spec_from_file_location("tenant_webhook_uniqueness_revision", revision_path)
    assert spec is not None
    assert spec.loader is not None

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260515_0004"
    assert module.down_revision == "20260515_0003"
    assert '"uq_webhook_provider_event", "webhook_events", type_="unique"' in source
    assert '"uq_webhook_tenant_provider_event"' in source
    assert '["tenant_id", "provider", "provider_event_id"]' in source
    assert '_duplicate_count("tenant_id, provider, provider_event_id")' in source
    assert '_duplicate_count("provider, provider_event_id")' in source


def test_tenant_composite_relationship_revision_follows_webhook_uniqueness():
    backend_dir = Path(__file__).resolve().parents[1]
    revision_path = backend_dir / "migrations" / "versions" / "20260515_0005_tenant_composite_relationships.py"
    source = revision_path.read_text()
    spec = spec_from_file_location("tenant_composite_relationship_revision", revision_path)
    assert spec is not None
    assert spec.loader is not None

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260515_0005"
    assert module.down_revision == "20260515_0004"
    assert {name for name, _table, _columns in module.SUPPORTING_UNIQUES} == {
        "uq_customers_tenant_id_id",
        "uq_conversations_tenant_id_id",
        "uq_broadcasts_tenant_id_id",
    }
    assert {name for name, _source, _target, _local, _remote, _ondelete in module.COMPOSITE_FOREIGN_KEYS} == {
        "fk_conversations_tenant_customer",
        "fk_messages_tenant_conversation",
        "fk_tickets_tenant_conversation",
        "fk_broadcast_recipients_tenant_broadcast",
        "fk_broadcast_recipients_tenant_customer",
        "fk_intent_keywords_tenant_intent",
        "fk_routing_rules_tenant_intent",
    }
    assert len(module.PREFLIGHT_CHECKS) == 7
    assert "c.tenant_id <> cu.tenant_id" in source
    assert "m.tenant_id <> c.tenant_id" in source
    assert "t.tenant_id <> c.tenant_id" in source
    assert "br.tenant_id <> b.tenant_id" in source
    assert "br.tenant_id <> c.tenant_id" in source
    assert "idf.id IS NULL" in source
    assert source.count("op.drop_constraint(name, source_table, type_=\"foreignkey\")") == 1
    assert source.count("op.drop_constraint(name, table_name, type_=\"unique\")") == 1
