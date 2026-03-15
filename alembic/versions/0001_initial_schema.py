"""Initial schema: RBAC tables + audit/tool-call logs

Revision ID: 0001
Revises:
Create Date: 2026-03-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clearance_levels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("level_order", sa.Integer, unique=True, nullable=False),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("clearance_ceiling_id", sa.Integer,
                  sa.ForeignKey("clearance_levels.id"), nullable=False),
        sa.Column("allowed_tools", sa.JSON, nullable=False),
    )

    op.create_table(
        "departments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("max_clearance_id", sa.Integer,
                  sa.ForeignKey("clearance_levels.id"), nullable=False),
        sa.Column("permitted_tools", sa.JSON, nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(128), unique=True, nullable=False),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("department_id", sa.Integer,
                  sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )

    op.create_table(
        "audit_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("clearance_level", sa.Integer, nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("response_hash", sa.String(80), nullable=False),
        sa.Column("tools_used", sa.JSON, nullable=False),
        sa.Column("data_classifications_accessed", sa.JSON, nullable=False),
        sa.Column("stripped_classifications", sa.JSON, nullable=False),
        sa.Column("iteration_count", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
    )

    op.create_table(
        "tool_call_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("thread_id", sa.String(128), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("tool_name", sa.String(64), nullable=False, index=True),
        sa.Column("inputs_json", sa.Text, nullable=False),
        sa.Column("output_snippet", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tool_call_logs")
    op.drop_table("audit_records")
    op.drop_table("users")
    op.drop_table("departments")
    op.drop_table("roles")
    op.drop_table("clearance_levels")
