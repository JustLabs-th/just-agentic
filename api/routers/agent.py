"""
Agent router — SSE streaming for LangGraph execution.

Architecture (Phase 1 — stateless):
  POST /api/agent/chat
    → enqueue ARQ job (worker runs LangGraph, publishes to Redis Stream)
    → relay events from Redis Stream to client via SSE

  POST /api/agent/resume/{thread_id}
    → clear old stream, enqueue ARQ resume job
    → relay new events from Redis Stream
"""

import json
from uuid import uuid4
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.schemas import ChatRequest, ResumeRequest
from api.deps import get_current_user
from api.redis_client import get_arq_pool, get_relay_redis
from security.jwt_auth import UserContext

router = APIRouter()

# How long (ms) each XREAD call blocks waiting for new stream entries.
# If no events arrive within this window the relay loops and tries again.
_XREAD_BLOCK_MS = 30_000


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── Redis Stream relay ─────────────────────────────────────────────────────────

async def _relay_stream(stream_key: str) -> AsyncGenerator[str, None]:
    """
    Read SSE events from a Redis Stream and yield them as SSE strings.
    Terminates when the worker publishes the `__done__` sentinel.
    """
    redis = get_relay_redis()
    last_id = "0"  # start from the beginning — handles worker starting before relay
    try:
        while True:
            entries = await redis.xread(
                {stream_key: last_id},
                block=_XREAD_BLOCK_MS,
                count=20,
            )
            if not entries:
                # Timeout — check if the worker ever created the stream
                if not await redis.exists(stream_key):
                    yield _sse("error", {"error": "Worker did not start — check worker logs"})
                # Either way, nothing more to relay
                return

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
