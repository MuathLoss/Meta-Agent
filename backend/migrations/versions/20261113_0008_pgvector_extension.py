"""Enable pgvector for knowledge search (spec v1.2, T05).

Revision ID: 20261113_0008
Revises: 20260910_0007
Create Date: 2026-11-13
"""
from alembic import op

revision = "20261113_0008"
down_revision = "20260910_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Needs a PostgreSQL image that ships pgvector (pgvector/pgvector:*-pg16 in compose).
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")
