"""
Local execution delegation via Redis.

When a CLI session requests local_exec mode, tool calls are delegated to
the client (which has /workspace + host tools mounted) via a Redis round-trip:

  Worker → XADD sse:{thread_id} tool_call_request
         → BLPOP tool_result:{call_id}   (blocks until client responds)
  Client → executes tool locally
         → POST /api/agent/tool-result/{thread_id}
  API    → LPUSH tool_result:{call_id}
  Worker → unblocks, continues graph
"""

import contextvars
import json
import os
import uuid

import redis as _redis_lib

_thread_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_local_exec_thread_id", default=None
)
_enabled_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_local_exec_enabled", default=False
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_TIMEOUT_BUFFER = 30  # extra seconds beyond tool timeout before giving up


def enable(thread_id: str) -> None:
    """Enable local execution mode for this context (thread/coroutine)."""
    _thread_id_ctx.set(thread_id)
    _enabled_ctx.set(True)


def is_enabled() -> bool:
    return _enabled_ctx.get()


def execute(tool_name: str, inputs: dict, workspace: str, timeout: int) -> str:
    """
    Delegate tool execution to the CLI client via Redis.
    Blocks until the client posts the result or the timeout fires.
    """
    thread_id = _thread_id_ctx.get()
    if not thread_id:
        return "Error: local_exec mode active but thread_id not in context"

    call_id = str(uuid.uuid4())
    r = _redis_lib.from_url(REDIS_URL, decode_responses=True)
    try:
        # Publish tool_call_request into the SSE stream so the relay forwards it
        stream_key = f"sse:{thread_id}"
        r.xadd(stream_key, {"data": json.dumps({
            "type":    "tool_call_request",
            "call_id": call_id,
            "tool":    tool_name,
            "input":   inputs,
        })})

        # Block until client posts the result
        result_key = f"tool_result:{call_id}"
        pair = r.blpop(result_key, timeout=timeout + _TIMEOUT_BUFFER)
        if pair is None:
            return f"Error: local tool execution timed out after {timeout + _TIMEOUT_BUFFER}s"

        try:
            return json.loads(pair[1]).get("output", "")
        except Exception:
            return str(pair[1])
    finally:
        r.close()
