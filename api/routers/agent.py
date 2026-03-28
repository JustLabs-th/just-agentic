"""
Agent router — SSE streaming for LangGraph execution.

Endpoints:
  POST /api/agent/chat           — start a new task, stream SSE events
  POST /api/agent/resume/{id}    — resume after human-approval interrupt
"""

import asyncio
import json
from uuid import uuid4
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from langgraph.types import Command

from api.schemas import ChatRequest, ResumeRequest
from api.deps import get_current_user
from graph.state import AgentState
from graph.secure_graph import build_secure_graph
from security.jwt_auth import UserContext

router = APIRouter()

# Single compiled graph shared across requests
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_secure_graph()
    return _graph


# ── SSE helpers ──────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _build_state(request: ChatRequest, user: UserContext) -> AgentState:
    """Build initial AgentState from HTTP request."""
    history = []
    for m in request.history:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "user":
            history.append(HumanMessage(content=content))
        elif role == "assistant":
            history.append(AIMessage(content=content))

    return {
        "messages":      history + [HumanMessage(content=request.message)],
        "jwt_token":       "",
        "user_id":         user.user_id,
        "user_role":       user.role,
        "user_department": user.department,
        "clearance_level": 0,
        "allowed_tools":   [],
        "context":         [],
        "visible_context": [],
        "stripped_levels": [],
        "data_classifications_accessed": [],
        "user_goal":       request.message,
        "current_agent":   "supervisor",
        "plan":            [],
        "goal_for_agent":  "",
        "working_memory":  {},
        "tools_called":    [],
        "iteration":       0,
        "intent":          "",
        "confidence":      0.0,
        "routing_history": [],
        "retry_count":     {},
        "supervisor_log":  [],
        "final_answer":    "",
        "status":          "planning",
        "error":           "",
        "audit_trail":     [],
    }


# ── Core streaming logic ──────────────────────────────────────────────────────

async def _stream_graph(app, input_, config: dict) -> AsyncGenerator[str, None]:
    """
    Run LangGraph's sync stream() in a thread pool and yield SSE strings.
    Deduplicates messages by tracking seen message IDs.
    """
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=200)

    def _worker():
        try:
            current_agent: list[str | None] = [None]
            seen_msg_ids: set = set()

            for event in app.stream(input_, config, stream_mode="values"):
                s = event
                chunks: list[str] = []

                # Agent switch notification
                active = s.get("current_agent", "")
                if active and active != current_agent[0] and active not in ("supervisor",):
                    current_agent[0] = active
                    chunks.append(_sse("agent_switch", {
                        "agent":      active,
                        "intent":     s.get("intent", ""),
                        "confidence": s.get("confidence", 0.0),
                    }))

                # Permission denied — terminal
                if s.get("status") == "permission_denied":
                    chunks.append(_sse("permission_denied", {
                        "error": s.get("error", "Permission denied"),
                    }))
                    for c in chunks:
                        loop.call_soon_threadsafe(queue.put_nowait, c)
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                    return

                # New AI messages (deduplicated by id)
                for msg in s.get("messages", []):
                    if isinstance(msg, AIMessage) and msg.content:
                        msg_id = getattr(msg, "id", None) or id(msg)
                        if msg_id not in seen_msg_ids:
                            seen_msg_ids.add(msg_id)
                            content = msg.content
                            if isinstance(content, list):
                                content = " ".join(
                                    p.get("text", "") if isinstance(p, dict) else str(p)
                                    for p in content
                                )
                            if content.strip():
                                chunks.append(_sse("message", {
                                    "content": content,
                                    "role":    "assistant",
                                }))

                # Done / error — terminal
                if s.get("status") in ("done", "error"):
                    # Safety net: emit final_answer as message if nothing was sent yet
                    final = s.get("final_answer", "")
                    if final and not seen_msg_ids:
                        chunks.append(_sse("message", {
                            "content": final,
                            "role":    "assistant",
                        }))
                    chunks.append(_sse("done", {
                        "status":       s.get("status"),
                        "final_answer": final,
                        "error":        s.get("error", ""),
                    }))
                    for c in chunks:
                        loop.call_soon_threadsafe(queue.put_nowait, c)
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                    return

                for c in chunks:
                    loop.call_soon_threadsafe(queue.put_nowait, c)

            # Stream ended — check for pending interrupts (human approval)
            graph_state = app.get_state(config)
            if graph_state and graph_state.next:
                for task_info in graph_state.tasks or []:
                    for intr in getattr(task_info, "interrupts", None) or []:
                        loop.call_soon_threadsafe(queue.put_nowait, _sse("approval_required", {
                            "agent":  intr.value.get("agent", "agent"),
                            "intent": intr.value.get("intent", ""),
                            "action": intr.value.get("action", ""),
                        }))
                        loop.call_soon_threadsafe(queue.put_nowait, None)
                        return

            # Fallback sentinel
            loop.call_soon_threadsafe(queue.put_nowait, _sse("done", {
                "status": "done", "final_answer": "", "error": "",
            }))
            loop.call_soon_threadsafe(queue.put_nowait, None)

        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, _sse("error", {"error": str(exc)}))
            loop.call_soon_threadsafe(queue.put_nowait, None)

    worker_task = asyncio.ensure_future(asyncio.to_thread(_worker))

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    await worker_task


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
):
    app = _get_graph()
    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    state = _build_state(request, user)

    async def event_stream():
        # First event: thread_id so the client can resume after approval
        yield _sse("thread_id", {"thread_id": thread_id})
        async for chunk in _stream_graph(app, state, config):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Thread-Id":  thread_id,
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
        },
    )


@router.post("/resume/{thread_id}")
async def resume(
    thread_id: str,
    request: ResumeRequest,
    user: UserContext = Depends(get_current_user),
):
    app = _get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    async def event_stream():
        async for chunk in _stream_graph(app, Command(resume=request.approved), config):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
