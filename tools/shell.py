import subprocess
from langchain_core.tools import tool
from tools._safety import check_command, get_workspace, log_tool_call
from tools._permission import permission_required, _clearance_ctx
from tools._tool_client import call as tool_service_call, is_enabled as tool_service_enabled
from tool_service.executor import run_command as sandboxed_run
from security.output_classifier import check_output_clearance


@tool
@permission_required("run_shell")
def run_shell(command: str) -> str:
    """Run a shell/bash command and return stdout + stderr.

    Use for: docker, git, ls, cat, grep, curl, pip, go commands, etc.
    Timeout: 60 seconds.
    """
    blocked = check_command(command)
    if blocked:
        log_tool_call("run_shell", {"command": command}, blocked)
        return blocked

    workspace = get_workspace()
    ws_str = str(workspace) if workspace else None

    # Option B: route through isolated Tool Service container
    if tool_service_enabled():
        output = tool_service_call("run_shell", {"command": command}, ws_str, timeout=60)
    else:
        # Option A: run locally with OS resource limits
        output = sandboxed_run(command, ws_str, timeout=60)

    redacted = check_output_clearance("(shell output)", output, _clearance_ctx.get())
    if redacted:
        log_tool_call("run_shell", {"command": command}, redacted)
        return redacted
    log_tool_call("run_shell", {"command": command}, output)
    return output


@tool
def git_status() -> str:
    """Show git status, recent log, and diff summary of the current repository."""
    workspace = get_workspace()
    ws_str = str(workspace) if workspace else None
    commands = [
        "git status --short",
        "git log --oneline -5",
        "git diff --stat HEAD",
    ]
    parts = []
    for cmd in commands:
        # git_status is read-only — run locally (no need for tool service isolation)
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15,
            cwd=ws_str,
        )
        out = (result.stdout or result.stderr or "(no output)").strip()
        parts.append(f"$ {cmd}\n{out}")

    output = "\n\n".join(parts)
    log_tool_call("git_status", {}, output)
    return output
