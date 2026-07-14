"""pii_vault table + RLS

Revision ID: 0002_pii_vault
Revises: 0001_init
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_pii_vault"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pii_vault",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token", sa.String(80), primary_key=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_pii_vault_document", "pii_vault", ["document_id"])

    # Same RLS pattern as the other tenant-scoped tables.
    op.execute("ALTER TABLE pii_vault ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pii_vault FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY pii_vault_tenant_isolation ON pii_vault
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS pii_vault_tenant_isolation ON pii_vault")
    op.execute("ALTER TABLE pii_vault DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_pii_vault_document", table_name="pii_vault")
    op.drop_table("pii_vault")
