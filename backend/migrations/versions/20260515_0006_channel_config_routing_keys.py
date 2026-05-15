"""add non-secret channel config routing keys

Revision ID: 20260515_0006
Revises: 20260515_0005
Create Date: 2026-05-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260515_0006"
down_revision: Union[str, None] = "20260515_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROUTING_INDEXES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("uq_channel_configs_type_provider_channel_id", ("channel_type", "provider_channel_id"), True),
    ("ix_channel_configs_tenant_type_provider_channel", ("tenant_id", "channel_type", "provider_channel_id"), False),
    ("ix_channel_configs_type_status_provider_channel", ("channel_type", "status", "provider_channel_id"), False),
)


def _duplicate_provider_channel_count() -> int:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT channel_type, provider_channel_id
                FROM channel_configs
                WHERE provider_channel_id IS NOT NULL
                GROUP BY channel_type, provider_channel_id
                HAVING COUNT(*) > 1
            ) duplicates
            """
        )
    )
    return int(result.scalar() or 0)


def upgrade() -> None:
    op.add_column("channel_configs", sa.Column("provider_channel_id", sa.String(length=255), nullable=True))
    op.add_column("channel_configs", sa.Column("provider_account_id", sa.String(length=255), nullable=True))

    op.execute(
        """
        UPDATE channel_configs
        SET provider_channel_id = COALESCE(
            public_config_json ->> 'provider_channel_id',
            CASE
                WHEN channel_type = 'whatsapp' THEN public_config_json ->> 'phone_number_id'
                ELSE NULL
            END
        )
        WHERE provider_channel_id IS NULL
          AND (
            public_config_json ->> 'provider_channel_id' IS NOT NULL
            OR (
                channel_type = 'whatsapp'
                AND public_config_json ->> 'phone_number_id' IS NOT NULL
            )
          )
        """
    )
    op.execute(
        """
        UPDATE channel_configs
        SET provider_account_id = COALESCE(
            public_config_json ->> 'provider_account_id',
            CASE
                WHEN channel_type = 'whatsapp' THEN public_config_json ->> 'waba_id'
                ELSE NULL
            END
        )
        WHERE provider_account_id IS NULL
          AND (
            public_config_json ->> 'provider_account_id' IS NOT NULL
            OR (
                channel_type = 'whatsapp'
                AND public_config_json ->> 'waba_id' IS NOT NULL
            )
          )
        """
    )

    if _duplicate_provider_channel_count():
        raise RuntimeError("Cannot add channel routing uniqueness; duplicate channel_type/provider_channel_id rows exist.")

    op.create_index(
        "uq_channel_configs_type_provider_channel_id",
        "channel_configs",
        ["channel_type", "provider_channel_id"],
        unique=True,
        postgresql_where=sa.text("provider_channel_id IS NOT NULL"),
        sqlite_where=sa.text("provider_channel_id IS NOT NULL"),
    )
    op.create_index(
        "ix_channel_configs_tenant_type_provider_channel",
        "channel_configs",
        ["tenant_id", "channel_type", "provider_channel_id"],
    )
    op.create_index(
        "ix_channel_configs_type_status_provider_channel",
        "channel_configs",
        ["channel_type", "status", "provider_channel_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_configs_type_status_provider_channel", table_name="channel_configs")
    op.drop_index("ix_channel_configs_tenant_type_provider_channel", table_name="channel_configs")
    op.drop_index("uq_channel_configs_type_provider_channel_id", table_name="channel_configs")
    op.drop_column("channel_configs", "provider_account_id")
    op.drop_column("channel_configs", "provider_channel_id")
