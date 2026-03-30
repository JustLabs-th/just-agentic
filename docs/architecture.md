# Architecture

## System Overview

```
Browser / jag CLI
     │  POST /api/agent/chat  (Bearer token + message)
     ▼
FastAPI  (api/)                  ← stateless, scale horizontally
     │  enqueue ARQ job
     ▼
Redis Queue (ARQ)
     │  consume
     ▼
Worker  (worker.py)              ← runs LangGraph
     │  XADD SSE events
     ▼
Redis Stream  sse:{thread_id}
     │  XREAD BLOCK
     ▼
FastAPI SSE relay                ← yields text/event-stream to client
```

State is persisted across turns via **PostgresSaver** (or MemorySaver in tests).
All LLM and security logic runs in the Worker. The API is a thin HTTP/SSE proxy.

---

## LangGraph Pipeline

```
START
  → rbac_guard              validate role/JWT, populate allowed_tools + clearance_level
  → department_guard        intersect role ∩ dept tools, cap clearance to dept ceiling
  → agent_resolver          load user's bound agents from DB, enforce RBAC floor
  → data_classifier         strip DataChunks above user's clearance level
  → intent_guard            deterministic keyword block before LLM (write/exec patterns)
  → prompt_injection_guard  regex scan for injection patterns (override, jailbreak, leak)
  → supervisor              route to specialist agent (LLM call)
  → human_approval          interrupt() for dangerous actions (code_write / infra_write)
  → [backend|devops|qa|<custom>]  specialist agent with filtered tools
  → supervisor              review result, route next or finish
  → audit_log               write immutable record to audit_records table
END
```

Agents loop: `supervisor → human_approval → agent → supervisor` until `done=True` or max iterations (default 8).

---

## Defense in Depth (8 Layers)

| Layer | Node / Component | What it blocks |
|---|---|---|
| 1 | `rbac_guard` | Unknown roles, invalid/expired JWT tokens |
| 2 | `department_guard` | Over-privileged tool access across departments |
| 3 | `agent_resolver` | Binds agents to users, enforces RBAC floor on agent tools |
| 4 | `data_classifier` | Data chunks above user's effective clearance level |
| 5 | `intent_guard` | Write/exec keywords when tool not permitted (code, not LLM) |
| 6 | `prompt_injection_guard` | Instruction override, role hijack, jailbreak, prompt leak |
| 7 | `human_approval` | Dangerous actions via `interrupt()` |
| 8 | `@permission_required` | Last-resort tool-level check at execution time |

---

## Auth Modes

```
JWT mode  → rbac_guard calls decode_token(jwt_token)
            → validates exp, sub, role, dept claims
            → computes effective_clearance(role, dept)

Dev mode  → rbac_guard reads user_id/user_role/user_department directly from state

Credentials → POST /api/auth/login  {"mode": "credentials", "user_id": "...", "password": "..."}
              → bcrypt verify against users table → issues JWT
```

---

## Checkpoint Backend

| `DATABASE_URL` set? | Checkpointer |
|---|---|
| Yes | PostgresSaver (LangGraph) — persistent across restarts, multi-instance safe |
| No | MemorySaver — ephemeral, for testing / local dev |

---

## ABAC — Dynamic Agents

Super-admins create `AgentDefinition` rows in the DB. `agent_resolver` loads them on every request.

```
effective_tools = agent.allowed_tools ∩ user.role.allowed_tools ∩ user.dept.permitted_tools
```

Users with no agent bindings fall back to the 4 default agents (`backend`, `devops`, `qa`, `developer`).
Users with exactly 1 agent bypass the supervisor LLM call entirely.

---

## Local Exec Mode (CLI)

When `jag` CLI sends `local_exec=true`, dangerous tools are delegated to the client:

```
Worker pauses on BLPOP tool_result:{call_id}
  → publishes tool_call_request to Redis Stream
  → SSE relay forwards to CLI
CLI executes tool in /workspace (host OS — has Node.js, git, npm, etc.)
  → POSTs result to POST /api/agent/tool-result/{thread_id}
  → API does LPUSH tool_result:{call_id}
Worker unblocks, continues graph
```

---

## Module Map

```
main.py                          CLI entry — init_db, login (JWT/credentials/dev), stream, interrupt
main_client.py                   Thin CLI client — SSE relay only, local exec, no LangGraph
ja / jag                         Shell wrapper — docker run thin client pointing at JA_SERVER
worker.py                        ARQ worker — run_graph_job, resume_graph_job → publishes SSE events

api/
  main.py                        FastAPI app — CORS, startup init_db+init_redis, health check
  deps.py                        Dependency injection — get_current_user() from Bearer token
  schemas.py                     Pydantic request/response models (all endpoints)
  redis_client.py                ARQ pool + relay Redis connection pool — init/close on startup
  routers/
    auth.py                      POST /api/auth/login (JWT/credentials/dev)
                                 GET+POST /api/auth/setup (first-run admin creation)
    agent.py                     POST /api/agent/chat — enqueue + relay Redis Stream
                                 POST /api/agent/resume/{thread_id} — resume after approval
                                 POST /api/agent/tool-result/{thread_id} — local exec result
    admin/
      __init__.py                Combined admin router (prefix /api/admin)
      _agents.py                 Agent CRUD + user–agent bindings (9 routes)
      _users.py                  User management: list, create, update (3 routes)
      _mcp.py                    MCP server registry: register, toggle, delete (4 routes)
    knowledge.py                 Upload/list/delete RAG knowledge documents

graph/
  secure_graph.py                Builds and compiles the LangGraph graph, manages cache
  state.py                       AgentState TypedDict — single unified state (25+ fields)
  state_builder.py               build_initial_state() factory — shared by API + worker
  supervisor.py                  Routing + intent/confidence/retry/loop detection (only LLM node)
  agents/
    backend.py                   Code, API, bug fix specialist
    devops.py                    Docker, env, CI/CD specialist
    qa.py                        Test, log, verify specialist
    dynamic.py                   Runtime agent factory from DB AgentDefinition
  nodes/
    rbac_guard.py                JWT + plain credential validation, populate allowed_tools
    department_guard.py          Role ∩ dept tool intersection, clearance cap
    agent_resolver.py            Load user's agents from DB, enforce RBAC floor
    data_classifier.py           Clearance filtering for DataChunks in state["context"]
    intent_guard.py              Deterministic pre-check (write/exec patterns)
    prompt_injection_guard.py    15+ regex patterns for injection detection
    human_approval.py            interrupt() gate for code_write / infrastructure_write
    audit_log.py                 Writes immutable AuditRecord to DB

tools/
  __init__.py                    ALL_TOOLS list + TOOL_MAP dict (17 tools registered)
  shell.py                       run_shell
  file_ops.py                    read_file, write_file, edit_file, list_files, search_code, read_log
  code_exec.py                   execute_python, run_tests
  web_search.py                  web_search (DuckDuckGo, no API key)
  db_query.py                    query_db — read-only SQL (SELECT only, 200 row cap)
  scraper.py                     scrape_page — fetch URL → clean text (SSRF-safe allowlist)
  secrets_scan.py                scan_secrets — detect hardcoded credentials in files
  git_ops.py                     git_status
  knowledge_search.py            search_knowledge — RAG via pgvector + keyword fallback
  rag_utils.py                   Text chunker (paragraph-aware, overlapping windows)
  _permission.py                 @permission_required decorator + role/dept ContextVars
  _safety.py                     Path allowlist, command blocklist, tool_call_logs writer
  _tool_client.py                Routes run_shell/execute_python/run_tests → local exec / tool-service / local
  _local_exec.py                 Redis round-trip for CLI local tool delegation

security/
  rbac.py                        DB-backed roles + departments → tool sets + clearance ceiling
  classification.py              ClearanceLevel enum, DataChunk, filter_by_clearance()
  jwt_auth.py                    JWT decode/encode (PyJWT HS256), UserContext dataclass, make_dev_token()
  password.py                    bcrypt hash_password / verify_password
  output_classifier.py           Classifies tool output by file path + content patterns
  audit.py                       AuditLogger singleton — writes to audit_records table

db/
  models.py                      ORM: ClearanceLevel, Role, Department, User,
                                       AgentDefinition, UserAgentBinding,
                                       KnowledgeChunk, AuditRecord, ToolCallLog, MCPServer
  session.py                     Engine factory, get_db() context manager (PostgreSQL / SQLite)
  seed.py                        Idempotent default RBAC + agent definitions seeding

alembic/
  env.py                         Alembic config (auto-loads Base.metadata)
  versions/
    0001_initial_schema.py       Creates all base tables
    0002_add_new_tools.py        Adds query_db, scan_secrets, scrape_page to roles/depts
    0003_add_knowledge.py        KnowledgeChunk table + pgvector extension
    0004_add_agent_definitions.py  AgentDefinition + UserAgentBinding tables
    0005_add_mcp_servers.py      MCPServer table

llm/
  adapter.py                     LLMAdapter — OpenAI / OpenRouter / Anthropic / Ollama / vLLM
  embeddings.py                  OpenAI text-embedding-3-small adapter (for RAG)

tool_service/
  main.py                        FastAPI app — POST /execute (bearer auth), health check
  executor.py                    subprocess runner with RLIMIT_CPU/AS/FSIZE/NPROC limits

config/
  prompts.py                     System prompts for all agents + supervisor

frontend/
  src/app/                       Next.js app router pages (chat, admin, login)
  src/components/                Chat, approval, agent-switch UI components
  src/lib/                       SSE client, API helpers, auth

tests/
  test_rbac.py                   Roles, depts, effective_tools, effective_clearance
  test_permission.py             @permission_required with role+dept combinations
  test_prompt_injection.py       Blocked patterns + safe inputs
  test_output_classifier.py      Path/content classification
  test_intent_guard.py           Write/exec blocking
  test_department_guard.py       Tool reduction + clearance capping
  test_supervisor_routing.py     parse_decision, loop detection, max iterations
  test_jwt_auth.py               decode_token, make_dev_token, rbac_guard JWT path
  test_agent_resolver.py         Agent binding, RBAC floor enforcement, fallback
  test_audit_log.py              AuditRecord writes, append-only
  test_data_classifier.py        Clearance stripping for DataChunks
  test_knowledge_search.py       RAG vector + keyword search, clearance filtering
  test_graph_integration.py      Full pipeline: rbac → supervisor → agent → audit
```

---

## Data Models

| Model | Key fields |
|---|---|
| `Role` | name, clearance_ceiling, allowed_tools (JSON list) |
| `Department` | name, clearance_ceiling, permitted_tools (JSON list) |
| `User` | user_id, hashed_password, role_id, department_id, is_active |
| `AgentDefinition` | name, display_name, system_prompt, allowed_tools, department, is_active |
| `UserAgentBinding` | user_id, agent_name, created_by |
| `KnowledgeChunk` | doc_id, content, embedding (vector), clearance_level, department |
| `AuditRecord` | user_id, role, dept, clearance, query_hash, tools_used, status, created_at |
| `ToolCallLog` | user_id, tool_name, inputs_hash, output_classification, duration_ms |
| `MCPServer` | name, url, transport, description, is_active, created_by |

---

## RBAC Summary

| Role | Clearance | Tools |
|---|---|---|
| viewer | PUBLIC (1) | read_file, list_files, web_search |
| analyst | INTERNAL (2) | + search_code, git_status, read_log, query_db, scrape_page, scan_secrets, search_knowledge |
| manager | CONFIDENTIAL (3) | + run_shell, run_tests, get_env, execute_python |
| admin | SECRET (4) | all tools including write_file, edit_file |

Effective access = `role.allowed_tools ∩ dept.permitted_tools`, clearance = `min(role_ceiling, dept_ceiling)`.

---

## See Also

- [Request lifecycle](request-lifecycle.md) — step-by-step HTTP → SSE flow
- [Adding an agent](adding-an-agent.md) — Option A (API) and Option B (hardcoded node)
- [RBAC & data classification](rbac.md)
- [Supervisor routing logic](supervisor.md)
- [Tools & safety layer](tools.md)
- [LLM providers](llm-providers.md)
