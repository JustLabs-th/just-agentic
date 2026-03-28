"""Add knowledge_chunks table with pgvector support

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    # Enable pgvector extension (PostgreSQL only — no-op on SQLite)
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception:
        pass

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.String(128), nullable=False),
        sa.Column("document_name", sa.String(256), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("clearance_level", sa.Integer, nullable=False, server_default="1"),
        sa.Column("department", sa.String(64), nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_clearance", "knowledge_chunks", ["clearance_level"])

    # Add vector column (PostgreSQL only)
    try:
        op.add_column(
            "knowledge_chunks",
            sa.Column("embedding", sa.Text, nullable=True),  # placeholder type
        )
        op.execute(f"ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) USING NULL")
    except Exception:
        # SQLite / pgvector not available — embedding column stays as nullable Text
        pass


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
