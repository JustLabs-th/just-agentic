"""Shared safety helpers: path allowlist, command blocklist, tool logging."""

import json
import os
from contextvars import ContextVar
from pathlib import Path

# Paths that tools are NEVER allowed to read/write regardless of workspace
_BLOCKED_PATH_PREFIXES = [
    "/etc/shadow", "/etc/passwd", "/etc/sudoers",
    "/sys", "/proc", "/dev",
    "/private/etc",
]


def get_workspace() -> Path | None:
    """Return the workspace root if configured, else None (unrestricted)."""
    ws = os.getenv("WORKSPACE_ROOT", "").strip()
    return Path(ws).resolve() if ws and ws != "/absolute/path/to/your/project" else None


def resolve_path(path: str) -> Path:
    """Resolve a path: if relative, anchor to WORKSPACE_ROOT (or cwd).
    Absolute paths are used as-is.
    """
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    workspace = get_workspace()
    if workspace:
        return (workspace / p).resolve()
    return p.resolve()

# Shell command patterns that are never allowed
_BLOCKED_COMMAND_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "> /dev/sda",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",  # fork bomb
]

# Context vars — set by agent nodes before tool execution
_user_id_ctx:   ContextVar[str] = ContextVar("tool_user_id",  default="")
_thread_id_ctx: ContextVar[str] = ContextVar("tool_thread_id", default="")


def set_tool_context(user_id: str, thread_id: str = "") -> None:
    """Call in agent nodes alongside set_role_context, before create_react_agent."""
    _user_id_ctx.set(user_id)
    _thread_id_ctx.set(thread_id)


def check_path(path: str) -> str | None:
    """Return an error string if path is blocked, else None.

    Rules:
    1. Always block system paths (shadow, proc, etc.)
    2. If WORKSPACE_ROOT is set, block paths outside the workspace
    """
    resolved = resolve_path(path)
    resolved_str = str(resolved)

    for blocked in _BLOCKED_PATH_PREFIXES:
        if resolved_str.startswith(blocked):
            return f"BLOCKED: access to '{path}' is not allowed"

    workspace = get_workspace()
    if workspace:
        try:
            resolved.relative_to(workspace)
        except ValueError:
            return f"BLOCKED: '{path}' is outside the workspace ({workspace})"

    return None


def check_command(command: str) -> str | None:
    """Return an error string if command matches a blocked pattern, else None."""
    lower = command.lower().strip()
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern in lower:
            return f"BLOCKED: command matches unsafe pattern '{pattern}'"
    return None


def log_tool_call(tool_name: str, inputs: dict, output: str) -> None:
    """Append a tool call record to the tool_call_logs table."""
    try:
        from db.session import get_db
        from db.models import ToolCallLog

        with get_db() as db:
            db.add(ToolCallLog(
                thread_id=_thread_id_ctx.get() or None,
                user_id=_user_id_ctx.get() or None,
                tool_name=tool_name,
                inputs_json=json.dumps(inputs, default=str),
                output_snippet=output[:500],
            ))
    except Exception:
        pass  # logging failure must never crash the tool
