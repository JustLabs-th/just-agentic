"""
ARQ worker — consumes tasks from Redis queue, runs LangGraph, streams SSE events
back via Redis Streams so any API instance can relay them to the client.

Run locally:
  arq worker.WorkerSettings

Via Docker Compose:
  docker compose up worker

Environment variables (same as API):
  REDIS_URL        — default redis://localhost:6379
  DATABASE_URL     — PostgreSQL
  OPENAI_API_KEY   — or other LLM provider vars
  WORKSPACE_ROOT   — path to workspace directory
  MAX_ITERATIONS   — graph loop cap
  CONFIDENCE_THRESHOLD
"""

import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

import redis as syncredis  # sync client — used inside the graph-running thread
from arq.connections import RedisSettings
from langchain_core.messages import AIMessage
from langgraph.types import Command

from graph.secure_graph import build_secure_graph
from graph.state_builder import build_initial_state

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM_TTL = 300  # seconds to retain stream after completion

# ── Graph singleton (one per worker process) ──────────────────────────────────

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_secure_graph()
    return _graph


# ── Core: run graph sync, publish events to Redis Stream ──────────────────────

def _run_graph_sync(input_, config: dict, stream_key: str) -> None:
    """
    Run the LangGraph graph synchronously (blocking) and publish each SSE event
    to the Redis Stream at `stream_key`.  Called via asyncio.to_thread().
    """
    r = syncredis.from_url(REDIS_URL, decode_responses=True)

    def pub(event_type: str, data: dict) -> None:
        payload = json.dumps({"type": event_type, **data})
        r.xadd(stream_key, {"data": payload})

    try:
        app = _get_graph()
        current_agent: list[str | None] = [None]
        emitted_count: list[int] = [0]

        for event in app.stream(input_, config, stream_mode="values"):
            s = event

            # Agent switch
            active = s.get("current_agent", "")
            if active and active != current_agent[0] and active not in ("supervisor",):
                current_agent[0] = active
                pub("agent_switch", {
                    "agent":      active,
                    "intent":     s.get("intent", ""),
                    "confidence": s.get("confidence", 0.0),
                })

            # Permission denied — terminal
            if s.get("status") == "permission_denied":
                pub("permission_denied", {"error": s.get("error", "Permission denied")})
                pub("__done__", {})
                return

            # New messages — only emit since last snapshot
            all_msgs = s.get("messages", [])
            new_msgs = all_msgs[emitted_count[0]:]
            for msg in new_msgs:
                if isinstance(msg, AIMessage):
                    for tc in (getattr(msg, "tool_calls", None) or []):
                        pub("tool_call", {
                            "tool":  tc.get("name", ""),
                            "input": tc.get("args", {}),
                            "agent": current_agent[0] or "",
                        })
                    content = msg.content
                    if content:
                        if isinstance(content, list):
                            content = " ".join(
                                p.get("text", "") if isinstance(p, dict) else str(p)
                                for p in content
                                if not (isinstance(p, dict) and p.get("type") == "tool_use")
                            )
                        if isinstance(content, str) and content.strip():
                            pub("message", {"content": content, "role": "assistant"})
            emitted_count[0] = len(all_msgs)

            # Terminal states
            if s.get("status") in ("done", "error"):
                pub("done", {
                    "status":       s.get("status"),
                    "final_answer": s.get("final_answer", ""),
                    "error":        s.get("error", ""),
                })
                pub("__done__", {})
                return

        # Stream ended — check for human-approval interrupt
        graph_state = app.get_state(config)
        if graph_state and graph_state.next:
            for task_info in graph_state.tasks or []:
                for intr in getattr(task_info, "interrupts", None) or []:
                    pub("approval_required", {
                        "agent":  intr.value.get("agent", "agent"),
                        "intent": intr.value.get("intent", ""),
                        "action": intr.value.get("action", ""),
                    })
                    pub("__done__", {})
                    return

        pub("done", {"status": "done", "final_answer": "", "error": ""})
        pub("__done__", {})

    except Exception as exc:
        pub("error", {"error": str(exc)})
        pub("__done__", {})
    finally:
        r.close()


# ── ARQ job functions ─────────────────────────────────────────────────────────

async def run_graph_job(
    ctx,
    *,
    thread_id: str,
    message: str,
    history: list,
    user_ctx: dict,
    image: str | None = None,
    local_exec: bool = False,
) -> None:
    """
    ARQ job: build AgentState, run graph, publish SSE events to Redis Stream.
    Enqueued by POST /api/agent/chat.

    local_exec=True: tools are delegated to the CLI client via Redis round-trip
    instead of running in tool-service or locally.
    """
    if local_exec:
        from tools._local_exec import enable as _enable_local_exec
        _enable_local_exec(thread_id)

    stream_key = f"sse:{thread_id}"
    config = {"configurable": {"thread_id": thread_id}}
    state = build_initial_state(message, history, user_ctx, image)

    await asyncio.to_thread(_run_graph_sync, state, config, stream_key)

    # Keep stream alive for STREAM_TTL seconds after completion so late-joining
    # relay subscribers can still catch up.
    await ctx["redis"].expire(stream_key, STREAM_TTL)


async def resume_graph_job(
    ctx,
    *,
    thread_id: str,
    approved: bool,
) -> None:
    """
    ARQ job: resume graph after human-approval interrupt.
    Enqueued by POST /api/agent/resume/{thread_id}.
    """
    stream_key = f"sse:{thread_id}"
    config = {"configurable": {"thread_id": thread_id}}

    await asyncio.to_thread(_run_graph_sync, Command(resume=approved), config, stream_key)

    await ctx["redis"].expire(stream_key, STREAM_TTL)


# ── Worker lifecycle ──────────────────────────────────────────────────────────

async def startup(ctx) -> None:
    """Warm up DB and graph once per worker process."""
    from db import init_db
    init_db()
    _get_graph()  # compile graph so first job isn't slow


# ── Worker settings ───────────────────────────────────────────────────────────

class WorkerSettings:
    on_startup  = startup
    functions   = [run_graph_job, resume_graph_job]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    max_jobs    = 20        # concurrent jobs per worker process
    job_timeout = 300       # hard kill after 5 min
