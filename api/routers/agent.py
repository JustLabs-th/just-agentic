"""
Agent router — SSE streaming for LangGraph execution.

Architecture (Phase 1 — stateless):
  POST /api/agent/chat
    → enqueue ARQ job (worker runs LangGraph, publishes to Redis Stream)
    → relay events from Redis Stream to client via SSE

  POST /api/agent/resume/{thread_id}
    → clear old stream, enqueue ARQ resume job
    → relay new events from Redis Stream

  POST /api/agent/tool-result/{thread_id}   (local_exec mode only)
    → CLI posts tool execution result here
    → API pushes it to Redis so the blocked worker can unblock
"""

import json
from uuid import uuid4
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.schemas import ChatRequest, ResumeRequest, ToolResultRequest
from api.deps import get_current_user
from api.redis_client import get_arq_pool, get_relay_redis
from security.jwt_auth import UserContext

router = APIRouter()

# How long (ms) each XREAD call blocks waiting for new stream entries.
_XREAD_BLOCK_MS = 30_000


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── Redis Stream relay ─────────────────────────────────────────────────────────

async def _relay_stream(stream_key: str) -> AsyncGenerator[str, None]:
    """
    Read SSE events from a Redis Stream and yield them as SSE strings.
    Terminates when the worker publishes the `__done__` sentinel.

    During local_exec mode the worker may pause for an extended period while
    waiting for the client to execute a tool — the relay keeps polling as long
    as the stream key exists, so it won't incorrectly close the connection.
    """
    redis = get_relay_redis()
    last_id = "0"  # start from beginning — handles worker starting before relay
    try:
        while True:
            entries = await redis.xread(
                {stream_key: last_id},
                block=_XREAD_BLOCK_MS,
                count=20,
            )
            if not entries:
                # Timeout — check if the stream exists at all
                if not await redis.exists(stream_key):
                    yield _sse("error", {"error": "Worker did not start — check worker logs"})
                    return
                # Stream exists but worker is paused (e.g., waiting for a local
                # tool result from the CLI client) — keep polling
                continue

            for _, messages in entries:
                for msg_id, fields in messages:
                    last_id = msg_id
                    data = json.loads(fields["data"])
                    if data.get("type") == "__done__":
                        return
                    yield f"data: {json.dumps(data)}\n\n"
    finally:
        await redis.aclose()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
):
    thread_id = request.thread_id or str(uuid4())

    await get_arq_pool().enqueue_job(
        "run_graph_job",
        thread_id=thread_id,
        message=request.message,
        history=request.history or [],
        image=request.image,
        local_exec=request.local_exec,
        user_ctx={
            "user_id":    user.user_id,
            "role":       user.role,
            "department": user.department,
        },
    )

    async def event_stream():
        yield _sse("thread_id", {"thread_id": thread_id})
        async for chunk in _relay_stream(f"sse:{thread_id}"):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Thread-Id":   thread_id,
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
    stream_key = f"sse:{thread_id}"

    # Delete the old stream so the relay starts fresh and doesn't replay
    # approval_required / __done__ events from the initial run.
    relay_redis = get_relay_redis()
    await relay_redis.delete(stream_key)
    await relay_redis.aclose()

    await get_arq_pool().enqueue_job(
        "resume_graph_job",
        thread_id=thread_id,
        approved=request.approved,
    )

    async def event_stream():
        async for chunk in _relay_stream(stream_key):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/tool-result/{thread_id}")
async def submit_tool_result(
    thread_id: str,
    body: ToolResultRequest,
    user: UserContext = Depends(get_current_user),
):
    """
    CLI client posts the result of a locally-executed tool here.
    The worker is blocking on BLPOP tool_result:{call_id} — pushing to that
    key unblocks it so the graph can continue.
    """
    redis = get_relay_redis()
    try:
        result_key = f"tool_result:{body.call_id}"
        await redis.lpush(result_key, json.dumps({"output": body.output}))
        await redis.expire(result_key, 300)
    finally:
        await redis.aclose()
    return {"ok": True}
