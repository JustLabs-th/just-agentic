"""
Tool-level permission check — last line of defense.
Reads role, department, and clearance from contextvars set by agent nodes.
"""

from contextvars import ContextVar
from functools import wraps

from security.rbac import effective_tools

_role_ctx:      ContextVar[str] = ContextVar("current_role",       default="")
_dept_ctx:      ContextVar[str] = ContextVar("current_dept",       default="all")
_clearance_ctx: ContextVar[int] = ContextVar("current_clearance",  default=0)


def set_role_context(role: str, department: str = "all", clearance: int = 0) -> None:
    """Call in every agent node before create_react_agent."""
    _role_ctx.set(role)
    _dept_ctx.set(department or "all")
    _clearance_ctx.set(clearance)


def get_role_context() -> tuple[str, str, int]:
    return _role_ctx.get(), _dept_ctx.get(), _clearance_ctx.get()


def permission_required(tool_name: str):
    """
    Decorator for dangerous tool functions.
    Checks role ∩ department — not role alone.

    Apply INSIDE @tool:
        @tool
        @permission_required("write_file")
        def write_file(...): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = _role_ctx.get()
            dept = _dept_ctx.get()
            if not role:
                # No identity context — deny rather than allow (fail-closed)
                return (
                    f"[PERMISSION DENIED] '{tool_name}' requires an authenticated "
                    f"session. No role context is set."
                )
            allowed = effective_tools(role, dept)
            if tool_name not in allowed:
                return (
                    f"[PERMISSION DENIED] '{tool_name}' is not available for "
                    f"role='{role}' department='{dept}'."
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
