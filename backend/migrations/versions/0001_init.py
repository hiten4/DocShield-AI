"""init schema + RLS

Revision ID: 0001_init
Revises:
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


TENANT_SCOPED_TABLES = [
    "users",
    "documents",
    "parents",
    "chunks_meta",
    "flagged_chunks",
    "audit_logs",
    "eval_runs",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Create enum types via raw SQL, then reference them with create_type=False
    op.execute("CREATE TYPE user_role AS ENUM ('user', 'admin')")
    op.execute("CREATE TYPE doc_status AS ENUM ('pending', 'processing', 'processed', 'failed', 'quarantined')")
    op.execute("CREATE TYPE component_type AS ENUM ('table', 'paragraph', 'list')")
    op.execute("CREATE TYPE flag_status AS ENUM ('pending', 'approved', 'rejected')")

    user_role = postgresql.ENUM("user", "admin", name="user_role", create_type=False)
    doc_status = postgresql.ENUM(
        "pending", "processing", "processed", "failed", "quarantined",
        name="doc_status", create_type=False,
    )
    comp_type = postgresql.ENUM("table", "paragraph", "list", name="component_type", create_type=False)
    flag_status = postgresql.ENUM("pending", "approved", "rejected", name="flag_status", create_type=False)

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", doc_status, nullable=False, server_default="pending"),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])

    op.create_table(
        "parents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("component_type", comp_type, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("page_no", sa.Integer),
        sa.Column("section_path", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_parents_tenant_document", "parents", ["tenant_id", "document_id"])

    op.create_table(
        "chunks_meta",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parents.id"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("suspected_injection", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("flag_reason", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_chunks_tenant_doc", "chunks_meta", ["tenant_id", "document_id"])

    op.create_table(
        "flagged_chunks",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chunks_meta.id"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", flag_status, nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_at", sa.DateTime),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_flagged_tenant", "flagged_chunks", ["tenant_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50)),
        sa.Column("resource_id", sa.String(200)),
        sa.Column("meta", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_tenant", "audit_logs", ["tenant_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("faithfulness", sa.Float),
        sa.Column("answer_relevancy", sa.Float),
        sa.Column("context_precision", sa.Float),
        sa.Column("context_recall", sa.Float),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_eval_tenant", "eval_runs", ["tenant_id"])

    for tbl in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {tbl}_tenant_isolation ON {tbl}
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )


def downgrade() -> None:
    for tbl in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
    for t in ["eval_runs", "audit_logs", "flagged_chunks", "chunks_meta", "parents", "documents", "users", "tenants"]:
        op.drop_table(t)
    for e in ["flag_status", "component_type", "doc_status", "user_role"]:
        op.execute(f"DROP TYPE IF EXISTS {e}")