"""Add query_db, scan_secrets, scrape_page to existing roles and departments

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-15
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tools to add per role (cumulative — only to roles that should have them)
_ROLE_ADDITIONS: dict[str, list[str]] = {
    "analyst": ["scan_secrets", "scrape_page"],
    "manager": ["scan_secrets", "scrape_page", "query_db"],
    "admin":   ["scan_secrets", "scrape_page", "query_db"],
}

# Tools to add per department
_DEPT_ADDITIONS: dict[str, list[str]] = {
    "engineering": ["scan_secrets", "scrape_page", "query_db"],
    "devops":      ["scrape_page", "query_db"],
    "qa":          ["scrape_page", "scan_secrets"],
    "data":        ["scrape_page", "query_db"],
    "security":    ["scan_secrets", "scrape_page", "query_db"],
    "all":         ["scan_secrets", "scrape_page", "query_db"],
}


def _append_tools(conn, table: str, name_col: str, tools_col: str, additions: dict[str, list[str]]) -> None:
    """For each row name in additions, append missing tools to the JSON array."""
    for name, new_tools in additions.items():
        row = conn.execute(
            text(f"SELECT {tools_col} FROM {table} WHERE {name_col} = :name"),
            {"name": name},
        ).fetchone()
        if row is None:
            continue
        existing: list[str] = row[0] or []
        to_add = [t for t in new_tools if t not in existing]
        if to_add:
            updated = existing + to_add
            conn.execute(
                text(f"UPDATE {table} SET {tools_col} = :tools WHERE {name_col} = :name"),
                {"tools": updated, "name": name},
            )


def upgrade() -> None:
    conn = op.get_bind()
    _append_tools(conn, "roles",       "name", "allowed_tools",   _ROLE_ADDITIONS)
    _append_tools(conn, "departments", "name", "permitted_tools",  _DEPT_ADDITIONS)


def downgrade() -> None:
    conn = op.get_bind()
    # Remove the added tools from roles
    for name, tools in _ROLE_ADDITIONS.items():
        row = conn.execute(
            text("SELECT allowed_tools FROM roles WHERE name = :name"), {"name": name}
        ).fetchone()
        if row:
            updated = [t for t in (row[0] or []) if t not in tools]
            conn.execute(
                text("UPDATE roles SET allowed_tools = :tools WHERE name = :name"),
                {"tools": updated, "name": name},
            )
    # Remove from departments
    for name, tools in _DEPT_ADDITIONS.items():
        row = conn.execute(
            text("SELECT permitted_tools FROM departments WHERE name = :name"), {"name": name}
        ).fetchone()
        if row:
            updated = [t for t in (row[0] or []) if t not in tools]
            conn.execute(
                text("UPDATE departments SET permitted_tools = :tools WHERE name = :name"),
                {"tools": updated, "name": name},
            )
