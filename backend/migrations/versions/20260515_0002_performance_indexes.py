"""add non-destructive tenant query performance indexes

Revision ID: 20260515_0002
Revises: 20260515_0001
Create Date: 2026-05-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260515_0002"
down_revision: Union[str, None] = "20260515_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_conversations_tenant_state_updated_at", "conversations", ("tenant_id", "state", "updated_at")),
    ("ix_conversations_tenant_updated_at", "conversations", ("tenant_id", "updated_at")),
    ("ix_messages_tenant_conversation_created_at", "messages", ("tenant_id", "conversation_id", "created_at")),
    ("ix_tickets_tenant_status_created_at", "tickets", ("tenant_id", "status", "created_at")),
    ("ix_tickets_tenant_priority_status", "tickets", ("tenant_id", "priority", "status")),
    ("ix_broadcasts_tenant_status_schedule_at", "broadcasts", ("tenant_id", "status", "schedule_at")),
    ("ix_broadcasts_tenant_created_by", "broadcasts", ("tenant_id", "created_by")),
    ("ix_broadcast_recipients_tenant_broadcast_status", "broadcast_recipients", ("tenant_id", "broadcast_id", "status")),
    ("ix_broadcast_recipients_tenant_customer_id", "broadcast_recipients", ("tenant_id", "customer_id")),
    ("ix_webhook_events_tenant_provider_event_id", "webhook_events", ("tenant_id", "provider", "provider_event_id")),
    ("ix_webhook_events_provider_event_type_created_at", "webhook_events", ("provider", "event_type", "created_at")),
    ("ix_channel_configs_channel_type_status", "channel_configs", ("channel_type", "status")),
    ("ix_channel_configs_tenant_channel_status", "channel_configs", ("tenant_id", "channel_type", "status")),
    ("ix_audit_logs_tenant_created_at", "audit_logs", ("tenant_id", "created_at")),
    ("ix_audit_logs_tenant_actor_created_at", "audit_logs", ("tenant_id", "actor_user_id", "created_at")),
    ("ix_audit_logs_tenant_entity", "audit_logs", ("tenant_id", "entity_type", "entity_id")),
    ("ix_customers_tenant_created_at", "customers", ("tenant_id", "created_at")),
    ("ix_faq_items_tenant_status", "faq_items", ("tenant_id", "status")),
    ("ix_intent_keywords_tenant_intent_code", "intent_keywords", ("tenant_id", "intent_code")),
)


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index_if_missing(name: str, table_name: str, columns: tuple[str, ...]) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, list(columns), unique=False)


def _drop_index_if_present(name: str, table_name: str) -> None:
    if name in _index_names(table_name):
        op.drop_index(name, table_name=table_name)


def upgrade() -> None:
    for name, table_name, columns in INDEXES:
        _create_index_if_missing(name, table_name, columns)


def downgrade() -> None:
    for name, table_name, _columns in reversed(INDEXES):
        _drop_index_if_present(name, table_name)
