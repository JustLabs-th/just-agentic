"""SQLAlchemy ORM models — single source of truth for all persisted data."""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── RBAC (admin-managed) ───────────────────────────────────────────────────────

class ClearanceLevel(Base):
    """Admin-defined clearance tiers. level_order determines hierarchy (higher = more access)."""
    __tablename__ = "clearance_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    level_order: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)


class Role(Base):
    """User role with a clearance ceiling and allowed tool list."""
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    clearance_ceiling_id: Mapped[int] = mapped_column(
        ForeignKey("clearance_levels.id"), nullable=False
    )
    allowed_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    clearance_ceiling: Mapped[ClearanceLevel] = relationship(
        "ClearanceLevel", foreign_keys=[clearance_ceiling_id]
    )
    users: Mapped[list["User"]] = relationship("User", back_populates="role")


class Department(Base):
    """Department narrows allowed tools and caps clearance below role ceiling."""
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    max_clearance_id: Mapped[int] = mapped_column(
        ForeignKey("clearance_levels.id"), nullable=False
    )
    permitted_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    max_clearance: Mapped[ClearanceLevel] = relationship(
        "ClearanceLevel", foreign_keys=[max_clearance_id]
    )
    users: Mapped[list["User"]] = relationship("User", back_populates="department")


class User(Base):
    """Application user — assigned one role and one department."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    role: Mapped[Role] = relationship("Role", back_populates="users")
    department: Mapped[Department] = relationship("Department", back_populates="users")


# ── LOGS (append-only) ────────────────────────────────────────────────────────

class AuditRecord(Base):
    """Immutable audit record written after every agent turn."""
    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    department: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    clearance_level: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    tools_used: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_classifications_accessed: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    stripped_classifications: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ToolCallLog(Base):
    """One row per tool execution — high-frequency append-only operational log."""
    __tablename__ = "tool_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_snippet: Mapped[str] = mapped_column(Text, nullable=False)
