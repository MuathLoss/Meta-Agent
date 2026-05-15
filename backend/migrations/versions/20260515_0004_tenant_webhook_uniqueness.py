"""make webhook event uniqueness tenant-aware

Revision ID: 20260515_0004
Revises: 20260515_0003
Create Date: 2026-05-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260515_0004"
down_revision: Union[str, None] = "20260515_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _duplicate_count(columns: str) -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT {columns}
                    FROM webhook_events
                    GROUP BY {columns}
                    HAVING COUNT(*) > 1
                ) duplicates
                """
            )
        )
        .scalar()
        or 0
    )


def upgrade() -> None:
    # Inserts must resolve and store tenant_id before writing webhook_events.
    # tenant_id remains nullable for ON DELETE SET NULL; future retention/archive
    # policy should decide how historical webhook rows survive tenant deletion.
    if _duplicate_count("tenant_id, provider, provider_event_id"):
        raise RuntimeError("Cannot create tenant-aware webhook uniqueness; duplicate tenant/provider/event rows exist.")

    op.drop_constraint("uq_webhook_provider_event", "webhook_events", type_="unique")
    op.create_unique_constraint(
        "uq_webhook_tenant_provider_event",
        "webhook_events",
        ["tenant_id", "provider", "provider_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_webhook_tenant_provider_event", "webhook_events", type_="unique")

    if _duplicate_count("provider, provider_event_id"):
        raise RuntimeError("Cannot restore global webhook uniqueness; duplicate provider/event rows exist.")

    op.create_unique_constraint(
        "uq_webhook_provider_event",
        "webhook_events",
        ["provider", "provider_event_id"],
    )
