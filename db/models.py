"""SQLAlchemy ORM models — single source of truth for all persisted data."""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

try:
    from pgvector.sqlalchemy import Vector
    _VECTOR_AVAILABLE = True
except ImportError:
    Vector = None
    _VECTOR_AVAILABLE = False


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
    agent_bindings: Mapped[list["UserAgentBinding"]] = relationship(
        "UserAgentBinding", back_populates="user"
    )


# ── ABAC — dynamic agent definitions ──────────────────────────────────────────

class AgentDefinition(Base):
    """A custom agent created by a super-admin and bound to specific users."""
    __tablename__ = "agent_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    bindings: Mapped[list["UserAgentBinding"]] = relationship(
        "UserAgentBinding", back_populates="agent_definition"
    )


class UserAgentBinding(Base):
    """Binds a user to a specific agent definition."""
    __tablename__ = "user_agent_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("users.user_id"), nullable=False
    )
    agent_definition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_definitions.id"), nullable=False
    )
    assigned_by: Mapped[str] = mapped_column(String(128), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship("User", back_populates="agent_bindings")
    agent_definition: Mapped[AgentDefinition] = relationship(
        "AgentDefinition", back_populates="bindings"
    )


# ── RAG Knowledge Base ────────────────────────────────────────────────────────

EMBEDDING_DIM = 1536  # OpenAI text-embedding-3-small


class KnowledgeChunk(Base):
    """One chunk of a knowledge document with its vector embedding."""
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_name: Mapped[str] = mapped_column(String(256), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    clearance_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # PUBLIC=1
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)  # None = all depts
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Vector column — only when pgvector is installed (PostgreSQL prod)
    if _VECTOR_AVAILABLE and Vector is not None:
        embedding: Mapped[list[float] | None] = mapped_column(
            Vector(EMBEDDING_DIM), nullable=True
        )


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
