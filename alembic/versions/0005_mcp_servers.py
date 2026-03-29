"""Add mcp_servers table

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id",          sa.Integer(),     primary_key=True),
        sa.Column("name",        sa.String(64),    nullable=False, unique=True),
        sa.Column("url",         sa.Text(),         nullable=False),
        sa.Column("transport",   sa.String(16),     nullable=False, server_default="sse"),
        sa.Column("description", sa.Text(),         nullable=False, server_default=""),
        sa.Column("is_active",   sa.Boolean(),      nullable=False, server_default=sa.true()),
        sa.Column("created_by",  sa.String(128),    nullable=False),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_mcp_servers_name", "mcp_servers", ["name"])


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_name", "mcp_servers")
    op.drop_table("mcp_servers")
