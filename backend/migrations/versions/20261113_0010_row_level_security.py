"""PostgreSQL row-level security on every tenant-owned table (spec v1.2, Section 8).

A row is visible or writable only when the transaction is scoped to its tenant
(app.rls_scope = 'tenant' and app.tenant_id = the row's tenant), or is trusted system work
(app.rls_scope = 'system': sign-in, webhooks, the worker). app/core/db.py sets both values at
the start of every transaction. Without either setting nothing is visible.

Policies bind the application role (scripts/setup_db_roles.py), not the table owner that runs
migrations: owners bypass row-level security unless it is forced, which is intended here.

Revision ID: 20261113_0010
Revises: 20261113_0009
Create Date: 2026-11-13
"""
from alembic import op

revision = "20261113_0010"
down_revision = "20261113_0009"
branch_labels = None
depends_on = None

# (table, column holding the tenant id)
TENANT_TABLES = [
    ("tenants", "id"),
    ("tenant_brands", "tenant_id"),
    ("tenant_user_roles", "tenant_id"),
    ("tenant_invites", "tenant_id"),
    ("chatbots", "tenant_id"),
    ("branches", "tenant_id"),
    ("business_settings", "tenant_id"),
    ("faq_items", "tenant_id"),
    ("intent_definitions", "tenant_id"),
    ("intent_keywords", "tenant_id"),
    ("routing_rules", "tenant_id"),
    ("training_examples", "tenant_id"),
    ("channel_configs", "tenant_id"),
    ("customers", "tenant_id"),
    ("conversations", "tenant_id"),
    ("messages", "tenant_id"),
    ("tickets", "tenant_id"),
    ("broadcasts", "tenant_id"),
    ("broadcast_recipients", "tenant_id"),
    ("webhook_events", "tenant_id"),
    ("audit_logs", "tenant_id"),
    ("import_jobs", "tenant_id"),
]
POLICY = "tenant_isolation"


def _condition(column: str) -> str:
    return (
        "current_setting('app.rls_scope', true) = 'system' OR ("
        "current_setting('app.rls_scope', true) = 'tenant' AND "
        f"{column} = NULLIF(current_setting('app.tenant_id', true), '')::integer)"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {POLICY} ON {table} USING ({_condition(column)}) WITH CHECK ({_condition(column)})")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, _column in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
