import os
from langchain_core.tools import tool
from tools._safety import log_tool_call, get_workspace
from tools._permission import permission_required
from tools._tool_client import call as tool_service_call, is_enabled as tool_service_enabled
from tool_service.executor import run_python as sandboxed_run_python, run_command as sandboxed_run


@tool
@permission_required("execute_python")
def execute_python(code: str) -> str:
    """Execute a Python code snippet and return the output.

    Runs in an isolated sandbox. Use print() to see output.
    Timeout: 30 seconds.
    """
    # Option B: route through isolated Tool Service container
    if tool_service_enabled():
        output = tool_service_call("execute_python", {"code": code}, timeout=30)
    else:
        # Option A: run locally with OS resource limits
        output = sandboxed_run_python(code, timeout=30)

    log_tool_call("execute_python", {"code_snippet": code[:100]}, output)
    return output


@tool
def run_tests(command: str = "pytest -q") -> str:
    """Run a test suite and return the full output.

    Default: pytest -q
    Examples: "pytest -q", "go test ./...", "npm test"
    Timeout: 120 seconds.
    """
    workspace = get_workspace()
    ws_str = str(workspace) if workspace else None

    # Option B: route through isolated Tool Service container
    if tool_service_enabled():
        output = tool_service_call("run_tests", {"command": command}, ws_str, timeout=120)
    else:
        # Option A: run locally with OS resource limits
        output = sandboxed_run(command, ws_str, timeout=120)

    log_tool_call("run_tests", {"command": command}, output)
    return output


@tool
def get_env(name: str) -> str:
    """Read an environment variable by name.

    Returns the value, or a message if not set.
    Never returns secrets in full — truncates values over 20 chars.
    """
    value = os.environ.get(name)
    if value is None:
        out = f"ENV '{name}' is not set"
    elif len(value) > 20:
        out = f"ENV '{name}' = {value[:4]}...{value[-4:]} (truncated, len={len(value)})"
    else:
        out = f"ENV '{name}' = {value}"
    log_tool_call("get_env", {"name": name}, out)
    return out
