import subprocess
from langchain_core.tools import tool
from tools._safety import check_command, log_tool_call
from tools._permission import permission_required, _clearance_ctx
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

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}"
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if not output:
            output = "(no output)"
        output += f"\nEXIT CODE: {result.returncode}"
    except subprocess.TimeoutExpired:
        output = "ERROR: Command timed out after 60 seconds"
    except Exception as e:
        output = f"ERROR: {e}"

    redacted = check_output_clearance("(shell output)", output, _clearance_ctx.get())
    if redacted:
        log_tool_call("run_shell", {"command": command}, redacted)
        return redacted
    log_tool_call("run_shell", {"command": command}, output)
    return output


@tool
def git_status() -> str:
    """Show git status, recent log, and diff summary of the current repository."""
    commands = [
        "git status --short",
        "git log --oneline -5",
        "git diff --stat HEAD",
    ]
    parts = []
    for cmd in commands:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        out = (result.stdout or result.stderr or "(no output)").strip()
        parts.append(f"$ {cmd}\n{out}")

    output = "\n\n".join(parts)
    log_tool_call("git_status", {}, output)
    return output
