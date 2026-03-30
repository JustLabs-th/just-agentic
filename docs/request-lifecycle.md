# Request Lifecycle

How a single chat message travels through the system from HTTP to SSE response.

---

## Overview

```
Browser / jag CLI
    │  POST /api/agent/chat  (Bearer token + message)
    ▼
FastAPI  (api/)            ← stateless, scale horizontally
    │  enqueue ARQ job
    ▼
Redis Queue               ← ARQ job queue
    │  consume job
    ▼
Worker  (worker.py)       ← runs LangGraph, 1–N workers
    │  XADD SSE events
    ▼
Redis Stream  sse:{thread_id}
    │  XREAD BLOCK (relay)
    ▼
FastAPI SSE relay         ← same API instance or different — doesn't matter
    │  text/event-stream
    ▼
Browser / jag CLI
```

---

## Step-by-Step

### 1. POST /api/agent/chat

**File:** `api/routers/agent.py`

- JWT validated by `api/deps.py` → `get_current_user()`
- `thread_id` generated if not provided
- Job enqueued to Redis via ARQ: `run_graph_job(thread_id, message, history, user_ctx, local_exec)`
- SSE stream opened immediately — client receives `{"type": "thread_id", "thread_id": "..."}` right away

### 2. ARQ Worker picks up the job

**File:** `worker.py`

- `run_graph_job()` called in worker process
- If `local_exec=True`: enables Redis delegation for tool calls (see [Local Exec Mode](#local-exec-mode))
- `build_initial_state()` called → constructs `AgentState` TypedDict
- `_run_graph_sync()` runs the LangGraph graph in a blocking thread

### 3. LangGraph security pipeline (8 nodes)

**File:** `graph/secure_graph.py` (wiring) + `graph/nodes/` (node implementations)

Each node receives `AgentState`, returns updated state. All are deterministic — no LLM.

```
rbac_guard
  → validates JWT or plain user_id/role/dept
  → populates state["allowed_tools"], state["clearance_level"]

department_guard
  → intersects role.allowed_tools ∩ dept.permitted_tools
  → caps clearance to min(role_ceiling, dept_ceiling)

agent_resolver
  → loads user's bound AgentDefinitions from DB
  → applies RBAC floor: agent.allowed_tools ∩ user.allowed_tools
  → falls back to default agents if no bindings found

data_classifier
  → strips state["context"] chunks where chunk.clearance > user clearance
  → records stripped levels in state["stripped_classifications"]

intent_guard
  → keyword-scans the user message for write/exec patterns
  → if blocked: sets state["status"] = "permission_denied" → graph ends

prompt_injection_guard
  → regex-scans for injection patterns (ignore previous, jailbreak, etc.)
  → if blocked: sets state["status"] = "permission_denied" → graph ends
```

### 4. Supervisor routing

**File:** `graph/supervisor.py`

- LLM call: "Which agent should handle this task?"
- Returns `{"agent": "backend", "intent": "code_write", "confidence": 0.88}`
- Single-agent bypass: if user has exactly 1 agent, skip LLM call entirely
- Loop detection: same agent 3× in a row → force FINISH
- Iteration cap: MAX_ITERATIONS (default 8) → force FINISH

### 5. Specialist agent executes

**File:** `graph/agents/backend.py` (or devops.py / qa.py / dynamic.py)

- `create_react_agent()` runs the ReAct loop: reason → tool call → observe → repeat
- Tools filtered by `state["allowed_tools"]` before binding
- Each tool call goes through `@permission_required` (final RBAC check)
- Dangerous tools (`run_shell`, `write_file`, etc.) may hit `human_approval` interrupt

### 6. Human approval (optional)

**File:** `graph/nodes/human_approval.py`

- If agent's intent is `code_write` or `infrastructure_write`: `interrupt()` fires
- Worker pauses, publishes `{"type": "approval_required"}` to Redis Stream
- Client sees the event and prompts the user
- User approves/rejects via `POST /api/agent/resume/{thread_id}`
- Worker resumes via `Command(resume=approved)`

### 7. Audit log

**File:** `graph/nodes/audit_log.py`

- Writes immutable `AuditRecord` to DB after every turn
- Records: user, role, dept, clearance, query hash, tools used, data classifications accessed, status

### 8. SSE events published

**File:** `worker.py` → `_run_graph_sync()`

Each graph state snapshot is scanned for:
- New `AIMessage` with `tool_calls` → publishes `{"type": "tool_call", ...}`
- New `AIMessage` with text content → publishes `{"type": "message", ...}`
- Agent switch detected → publishes `{"type": "agent_switch", ...}`
- Terminal status → publishes `{"type": "done", ...}` then `{"type": "__done__"}`

All events go to Redis Stream `sse:{thread_id}` via `XADD`.

### 9. SSE relay delivers to client

**File:** `api/routers/agent.py` → `_relay_stream()`

- `XREAD BLOCK` polls the Redis Stream
- Yields each event as `data: {...}\n\n`
- Stops when `__done__` sentinel received
- If stream doesn't exist after 30s timeout → yields error event

---

## Local Exec Mode

When `jag` CLI sends `local_exec=true`, tools are delegated to the client process:

```
Worker encounters run_shell / write_file / etc.
  │  XADD sse:{thread_id}  {"type": "tool_call_request", "call_id": "...", "tool": "...", "input": {...}}
  │  BLPOP tool_result:{call_id}   ← blocks here
  ▼
SSE relay forwards tool_call_request to CLI client

CLI client (_execute_local in main_client.py)
  → runs tool in /workspace (host OS — has Node.js, git, npm, etc.)
  → POST /api/agent/tool-result/{thread_id}  {"call_id": "...", "output": "..."}
  ▼
API router (agent.py /tool-result)
  → LPUSH tool_result:{call_id}
  ▼
Worker unblocks, continues graph
```

This allows the CLI client's host environment (Node.js v24, git, etc.) to be used
while all LLM / security / routing logic stays on the server.

---

## Resume Flow

After a human approval interrupt:

```
POST /api/agent/resume/{thread_id}  {"approved": true}
  → DELETE old Redis Stream (avoid replaying approval_required)
  → enqueue resume_graph_job(thread_id, approved)
  → relay new stream
Worker: Command(resume=approved) passed to graph
  → graph continues from the interrupted node
```

---

## Key Files Reference

| Step | File |
|------|------|
| HTTP entry point | `api/routers/agent.py` |
| Job queue | `api/redis_client.py` |
| Worker entry | `worker.py` |
| State factory | `graph/state_builder.py` |
| State definition | `graph/state.py` |
| Graph wiring | `graph/secure_graph.py` |
| Security nodes | `graph/nodes/` |
| Supervisor LLM | `graph/supervisor.py` |
| Agent nodes | `graph/agents/` |
| Tool execution | `tools/` |
| Tool routing | `tools/_tool_client.py` |
| CLI local exec | `tools/_local_exec.py` |
| SSE relay | `api/routers/agent.py` → `_relay_stream()` |
