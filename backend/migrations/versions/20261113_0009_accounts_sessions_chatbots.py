"""Accounts: server-side sessions, email links, invitations, owner role, one chatbot per tenant.

Revision ID: 20261113_0009
Revises: 20261113_0008
Create Date: 2026-11-13
"""
import secrets

import sqlalchemy as sa
from alembic import op

revision = "20261113_0009"
down_revision = "20261113_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    # Accounts created before verification existed are treated as verified.
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_slug", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(200)),
    )
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_tokens_token_hash", "user_tokens", ["token_hash"], unique=True)
    op.create_index("ix_user_tokens_user_id", "user_tokens", ["user_id"])

    op.create_table(
        "tenant_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role_code", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_invites_tenant_id", "tenant_invites", ["tenant_id"])
    op.create_index("ix_tenant_invites_token_hash", "tenant_invites", ["token_hash"], unique=True)

    op.create_table(
        "chatbots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("public_widget_id", sa.String(64), nullable=False),
        sa.Column("language_mode", sa.String(20), nullable=False, server_default="auto"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_chatbots_tenant_id_id"),
    )
    # Spec v1.2, P03: exactly one chatbot per institution.
    op.create_index("ix_chatbots_tenant_id", "chatbots", ["tenant_id"], unique=True)
    op.create_index("ix_chatbots_public_widget_id", "chatbots", ["public_widget_id"], unique=True)

    bind = op.get_bind()
    for tenant_id, name in bind.execute(sa.text("SELECT id, display_name FROM tenants")).fetchall():
        bind.execute(
            sa.text("INSERT INTO chatbots (tenant_id, display_name, status, public_widget_id, language_mode) VALUES (:t, :n, 'draft', :w, 'auto')"),
            {"t": tenant_id, "n": name, "w": "wb_" + secrets.token_urlsafe(16)},
        )
    # Each existing workspace's first administrator becomes its owner.
    rows = bind.execute(sa.text(
        "SELECT DISTINCT ON (tenant_id) tenant_id, user_id FROM tenant_user_roles "
        "WHERE role_code = 'BUSINESS_ADMIN' AND is_active ORDER BY tenant_id, created_at, id"
    ) if bind.dialect.name == "postgresql" else sa.text(
        "SELECT tenant_id, user_id FROM tenant_user_roles r WHERE role_code = 'BUSINESS_ADMIN' AND is_active "
        "AND id = (SELECT MIN(id) FROM tenant_user_roles x WHERE x.tenant_id = r.tenant_id AND x.role_code = 'BUSINESS_ADMIN' AND x.is_active)"
    )).fetchall()
    for tenant_id, user_id in rows:
        bind.execute(
            sa.text("INSERT INTO tenant_user_roles (tenant_id, user_id, role_code, is_active) "
                    "SELECT :t, :u, 'OWNER', true WHERE NOT EXISTS "
                    "(SELECT 1 FROM tenant_user_roles WHERE tenant_id = :t AND role_code = 'OWNER')"),
            {"t": tenant_id, "u": user_id},
        )


def downgrade() -> None:
    op.execute("DELETE FROM tenant_user_roles WHERE role_code = 'OWNER'")
    op.drop_table("chatbots")
    op.drop_table("tenant_invites")
    op.drop_table("user_tokens")
    op.drop_table("user_sessions")
    op.drop_column("users", "email_verified_at")
