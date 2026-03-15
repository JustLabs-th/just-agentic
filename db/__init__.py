"""Database package — models, session management, and initialization."""

from db.models import (
    Base,
    ClearanceLevel,
    Role,
    Department,
    User,
    AuditRecord,
    ToolCallLog,
)
from db.session import get_db, get_engine
from db.seed import seed_defaults


def init_db() -> None:
    """Create all tables and seed default RBAC data. Call once at application startup."""
    Base.metadata.create_all(get_engine())
    seed_defaults()


__all__ = [
    "init_db",
    "get_db",
    "get_engine",
    "Base",
    "ClearanceLevel",
    "Role",
    "Department",
    "User",
    "AuditRecord",
    "ToolCallLog",
]
