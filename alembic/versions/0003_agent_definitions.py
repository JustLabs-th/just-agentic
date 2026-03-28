"""Add agent_definitions and user_agent_bindings tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("allowed_tools", sa.JSON, nullable=False),
        sa.Column("department", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_definitions_name", "agent_definitions", ["name"])
    op.create_index("ix_agent_definitions_is_active", "agent_definitions", ["is_active"])

    op.create_table(
        "user_agent_bindings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(128), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column(
            "agent_definition_id",
            sa.Integer,
            sa.ForeignKey("agent_definitions.id"),
            nullable=False,
        ),
        sa.Column("assigned_by", sa.String(128), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.UniqueConstraint("user_id", "agent_definition_id", name="uq_user_agent"),
    )


def downgrade() -> None:
    op.drop_table("user_agent_bindings")
    op.drop_table("agent_definitions")
