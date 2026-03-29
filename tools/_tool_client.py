"""
Tool Service HTTP client — Option B routing layer.

When TOOL_SERVICE_URL is set (Docker/prod), dangerous tools (run_shell,
execute_python, run_tests) are routed to the isolated Tool Service container
instead of running locally.

When TOOL_SERVICE_URL is not set (local dev / tests), this module returns None
and the caller falls back to executing the subprocess locally.
"""

import os
import requests

_SERVICE_URL    = os.getenv("TOOL_SERVICE_URL", "").rstrip("/")
_SERVICE_SECRET = os.getenv("TOOL_SERVICE_SECRET", "")

# Request timeout = tool timeout + 10 s overhead
_OVERHEAD_S = 10


def is_enabled() -> bool:
    """True when Tool Service is configured — tools should route through it."""
    return bool(_SERVICE_URL)


def call(tool_name: str, inputs: dict, workspace: str | None = None, timeout: int = 60) -> str | None:
    """
    Call the Tool Service to execute a tool.

    Returns the output string on success.
    Returns None if Tool Service is not configured (caller should fall back).
    Raises RuntimeError on HTTP or connection errors.
    """
    if not _SERVICE_URL:
        return None

    headers = {}
    if _SERVICE_SECRET:
        headers["Authorization"] = f"Bearer {_SERVICE_SECRET}"

    try:
        resp = requests.post(
            f"{_SERVICE_URL}/execute",
            json={
                "tool":      tool_name,
                "inputs":    inputs,
                "workspace": workspace,
                "timeout":   timeout,
            },
            headers=headers,
            timeout=timeout + _OVERHEAD_S,
        )
        resp.raise_for_status()
        return resp.json()["output"]
    except requests.Timeout:
        return f"ERROR: Tool Service did not respond within {timeout + _OVERHEAD_S}s"
    except requests.ConnectionError:
        return f"ERROR: Cannot connect to Tool Service at {_SERVICE_URL}"
    except requests.HTTPError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            pass
        return f"ERROR: Tool Service returned {exc.response.status_code}: {detail or exc}"
