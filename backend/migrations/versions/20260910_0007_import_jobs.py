"""Add encrypted, tenant-owned resumable imports. Existing tables/data are untouched."""
from alembic import op
import sqlalchemy as sa
revision = "20260910_0007"
down_revision = "20260515_0006"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_import_jobs_tenant_id", "import_jobs", ["tenant_id"])
    op.create_index("ix_import_jobs_tenant_updated", "import_jobs", ["tenant_id", "updated_at"])

def downgrade():
    # Refuse to erase saved reviews/history through an accidental downgrade.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM import_jobs")).scalar()
    if count:
        raise RuntimeError("Import history exists. Export/review it before downgrading.")
    op.drop_table("import_jobs")
