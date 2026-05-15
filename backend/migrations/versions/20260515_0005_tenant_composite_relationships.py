"""add tenant-safe composite relationship constraints

Revision ID: 20260515_0005
Revises: 20260515_0004
Create Date: 2026-05-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260515_0005"
down_revision: Union[str, None] = "20260515_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PREFLIGHT_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "conversations.customer_id points to a customer with a different tenant_id",
        """
        SELECT COUNT(*)
        FROM conversations c
        JOIN customers cu ON c.customer_id = cu.id
        WHERE c.tenant_id <> cu.tenant_id
        """,
    ),
    (
        "messages.conversation_id points to a conversation with a different tenant_id",
        """
        SELECT COUNT(*)
        FROM messages m
        JOIN conversations c ON m.conversation_id = c.id
        WHERE m.tenant_id <> c.tenant_id
        """,
    ),
    (
        "tickets.conversation_id points to a conversation with a different tenant_id",
        """
        SELECT COUNT(*)
        FROM tickets t
        JOIN conversations c ON t.conversation_id = c.id
        WHERE t.tenant_id <> c.tenant_id
        """,
    ),
    (
        "broadcast_recipients.broadcast_id points to a broadcast with a different tenant_id",
        """
        SELECT COUNT(*)
        FROM broadcast_recipients br
        JOIN broadcasts b ON br.broadcast_id = b.id
        WHERE br.tenant_id <> b.tenant_id
        """,
    ),
    (
        "broadcast_recipients.customer_id points to a customer with a different tenant_id",
        """
        SELECT COUNT(*)
        FROM broadcast_recipients br
        JOIN customers c ON br.customer_id = c.id
        WHERE br.tenant_id <> c.tenant_id
        """,
    ),
    (
        "intent_keywords has no matching intent_definitions row for the same tenant_id and intent_code",
        """
        SELECT COUNT(*)
        FROM intent_keywords ik
        LEFT JOIN intent_definitions idf
          ON idf.tenant_id = ik.tenant_id
         AND idf.code = ik.intent_code
        WHERE idf.id IS NULL
        """,
    ),
    (
        "routing_rules has no matching intent_definitions row for the same tenant_id and intent_code",
        """
        SELECT COUNT(*)
        FROM routing_rules rr
        LEFT JOIN intent_definitions idf
          ON idf.tenant_id = rr.tenant_id
         AND idf.code = rr.intent_code
        WHERE idf.id IS NULL
        """,
    ),
)

SUPPORTING_UNIQUES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("uq_customers_tenant_id_id", "customers", ("tenant_id", "id")),
    ("uq_conversations_tenant_id_id", "conversations", ("tenant_id", "id")),
    ("uq_broadcasts_tenant_id_id", "broadcasts", ("tenant_id", "id")),
)

COMPOSITE_FOREIGN_KEYS: tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...], str], ...] = (
    (
        "fk_conversations_tenant_customer",
        "conversations",
        "customers",
        ("tenant_id", "customer_id"),
        ("tenant_id", "id"),
        "CASCADE",
    ),
    (
        "fk_messages_tenant_conversation",
        "messages",
        "conversations",
        ("tenant_id", "conversation_id"),
        ("tenant_id", "id"),
        "CASCADE",
    ),
    (
        "fk_tickets_tenant_conversation",
        "tickets",
        "conversations",
        ("tenant_id", "conversation_id"),
        ("tenant_id", "id"),
        "CASCADE",
    ),
    (
        "fk_broadcast_recipients_tenant_broadcast",
        "broadcast_recipients",
        "broadcasts",
        ("tenant_id", "broadcast_id"),
        ("tenant_id", "id"),
        "CASCADE",
    ),
    (
        "fk_broadcast_recipients_tenant_customer",
        "broadcast_recipients",
        "customers",
        ("tenant_id", "customer_id"),
        ("tenant_id", "id"),
        "CASCADE",
    ),
    (
        "fk_intent_keywords_tenant_intent",
        "intent_keywords",
        "intent_definitions",
        ("tenant_id", "intent_code"),
        ("tenant_id", "code"),
        "CASCADE",
    ),
    (
        "fk_routing_rules_tenant_intent",
        "routing_rules",
        "intent_definitions",
        ("tenant_id", "intent_code"),
        ("tenant_id", "code"),
        "CASCADE",
    ),
)


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar() or 0)


def _unique_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}


def _foreign_key_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {constraint["name"] for constraint in inspector.get_foreign_keys(table_name)}


def _run_preflight_checks() -> None:
    for label, sql in PREFLIGHT_CHECKS:
        if _count(sql):
            raise RuntimeError(f"Cannot add tenant-safe composite FKs: {label}.")


def upgrade() -> None:
    _run_preflight_checks()

    for name, table_name, columns in SUPPORTING_UNIQUES:
        if name not in _unique_names(table_name):
            op.create_unique_constraint(name, table_name, list(columns))

    for name, source_table, referent_table, local_cols, remote_cols, ondelete in COMPOSITE_FOREIGN_KEYS:
        if name not in _foreign_key_names(source_table):
            op.create_foreign_key(
                name,
                source_table,
                referent_table,
                list(local_cols),
                list(remote_cols),
                ondelete=ondelete,
            )


def downgrade() -> None:
    for name, source_table, _referent_table, _local_cols, _remote_cols, _ondelete in reversed(COMPOSITE_FOREIGN_KEYS):
        if name in _foreign_key_names(source_table):
            op.drop_constraint(name, source_table, type_="foreignkey")

    for name, table_name, _columns in reversed(SUPPORTING_UNIQUES):
        if name in _unique_names(table_name):
            op.drop_constraint(name, table_name, type_="unique")
