"""clean up legacy nullability drift

Revision ID: 20260515_0003
Revises: 20260515_0002
Create Date: 2026-05-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260515_0003"
down_revision: Union[str, None] = "20260515_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE intent_definitions SET supported_languages = 'ar' WHERE supported_languages IS NULL")
    op.execute("UPDATE intent_definitions SET response_mode = 'faq' WHERE response_mode IS NULL")
    op.execute("UPDATE conversations SET metadata_json = '{}' WHERE metadata_json IS NULL")

    op.alter_column(
        "intent_definitions",
        "supported_languages",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.alter_column(
        "intent_definitions",
        "response_mode",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.alter_column(
        "conversations",
        "metadata_json",
        existing_type=sa.JSON(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "conversations",
        "metadata_json",
        existing_type=sa.JSON(),
        nullable=True,
    )
    op.alter_column(
        "intent_definitions",
        "response_mode",
        existing_type=sa.String(length=20),
        nullable=True,
    )
    op.alter_column(
        "intent_definitions",
        "supported_languages",
        existing_type=sa.String(length=20),
        nullable=True,
    )
