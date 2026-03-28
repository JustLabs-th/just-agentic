"""
RBAC — Role-Based Access Control (DB-backed, admin-manageable).

Public interface is unchanged — guard nodes and tools call the same functions:
  get_policy(role)                → RolePolicy
  get_department_policy(dept)     → DepartmentPolicy
  effective_tools(role, dept)     → FrozenSet[str]
  effective_clearance(role, dept) → int
  is_tool_allowed(role, tool)     → bool
"""

from dataclasses import dataclass
from typing import FrozenSet

from db.session import get_db
from db.models import Role, Department, ClearanceLevel


@dataclass(frozen=True)
class RolePolicy:
    name: str
    clearance_ceiling: int
    allowed_tools: FrozenSet[str]


@dataclass(frozen=True)
class DepartmentPolicy:
    name: str
    permitted_tools: FrozenSet[str]
    max_clearance: int


class Clearance:
    """Dynamic clearance label lookup — reads from DB."""

    @classmethod
    def label(cls, level: int) -> str:
        try:
            with get_db() as db:
                row = db.query(ClearanceLevel).filter_by(level_order=level).first()
                return row.name if row else f"LEVEL({level})"
        except Exception:
            return f"LEVEL({level})"


def get_policy(role: str) -> RolePolicy:
    with get_db() as db:
        row = (
            db.query(Role)
            .filter_by(name=role)
            .join(Role.clearance_ceiling)
            .first()
        )
    if row is None:
        raise PermissionError(f"Unknown role: '{role}'")
    return RolePolicy(
        name=row.name,
        clearance_ceiling=row.clearance_ceiling.level_order,
        allowed_tools=frozenset(row.allowed_tools),
    )


def get_department_policy(department: str) -> DepartmentPolicy:
    with get_db() as db:
        row = (
            db.query(Department)
            .filter_by(name=department)
            .join(Department.max_clearance)
            .first()
        )
    if row is None:
        raise PermissionError(f"Unknown department: '{department}'")
    return DepartmentPolicy(
        name=row.name,
        permitted_tools=frozenset(row.permitted_tools),
        max_clearance=row.max_clearance.level_order,
    )


def effective_tools(role: str, department: str) -> FrozenSet[str]:
    """role.allowed_tools ∩ dept.permitted_tools"""
    return get_policy(role).allowed_tools & get_department_policy(department).permitted_tools


def effective_clearance(role: str, department: str) -> int:
    """min(role.clearance_ceiling, dept.max_clearance)"""
    return min(
        get_policy(role).clearance_ceiling,
        get_department_policy(department).max_clearance,
    )


def is_tool_allowed(role: str, tool_name: str, department: str = "all") -> bool:
    """Check tool permission against role ∩ department intersection.

    Always pass ``department`` — the default ``"all"`` is intentionally broad
    and exists only to preserve call-site compatibility during migration.
    """
    try:
        return tool_name in effective_tools(role, department)
    except PermissionError:
        return False
