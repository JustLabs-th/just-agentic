# Module Reference

Complete file-by-file guide. Every Python file in the project, grouped by directory.

---

## Root

### `main.py`
Interactive multi-turn CLI for local use. Calls `init_db()`, prompts for login (JWT / credentials / dev mode), then runs the compiled LangGraph graph in a REPL loop. Handles streaming output with a spinner, human approval interrupts, and graceful Ctrl-C. **Use this for local development** — no Redis or Docker required.

### `main_client.py`
Thin CLI client for the server mode (`jag` / Docker). Talks to the API over HTTP — does not run LangGraph locally. Handles SSE events, local tool execution via Redis round-trip (`local_exec=True`), human approval prompts, and UTF-8 sanitization for Docker TTY. **This is what `jag` runs.**

### `worker.py`
ARQ background worker. Consumes `run_graph_job` / `resume_graph_job` tasks from Redis. Runs the LangGraph synchronously in a thread, publishes SSE events to a Redis Stream (`sse:{thread_id}`) as the graph executes. Optionally enables local exec mode (`local_exec=True`) which delegates dangerous tools to the CLI client.

Key functions:
- `run_graph_job(thread_id, message, history, user_ctx, local_exec)` — main job
- `resume_graph_job(thread_id, approved)` — resumes after human approval
- `_run_graph_sync(graph, state, stream_key, redis)` — runs graph + publishes events

---

## `api/`

### `api/main.py`
FastAPI application root. Registers CORS (permissive for dev), mounts auth / agent / knowledge / admin routers, initializes DB (`init_db()`) and Redis (`init_redis_pool()`) on startup, closes them on shutdown. Exposes `GET /healthz`.

### `api/deps.py`
FastAPI dependency injection. `get_current_user()` extracts and validates the `Authorization: Bearer <token>` header, returning a `UserContext`. `require_admin()` wraps it and raises `403` if role is not `admin`.

### `api/schemas.py`
All Pydantic request/response models for the API. Covers: login, chat, tool results, agent CRUD, user management, MCP server registry, and knowledge base operations.

### `api/redis_client.py`
Manages two Redis connection pools:
- **ARQ pool** — for enqueueing background jobs (`arq.create_pool`)
- **Relay pool** — for `XREAD` / `XADD` / `LPUSH` / `BLPOP` during SSE relay and local exec

### `api/routers/auth.py`
Auth endpoints:
- `GET /api/auth/setup` — returns `{"needs_setup": true}` if no users exist
- `POST /api/auth/setup` — creates first admin user (fails if any user exists)
- `POST /api/auth/login` — supports three modes via `mode` field:
  - `jwt` — validates an existing Bearer token
  - `credentials` — bcrypt verify against `users` table, issues JWT
  - `dev` — issues JWT from `user_id/role/department` (no password, dev only)

### `api/routers/agent.py`
Core chat endpoints:
- `POST /api/agent/chat` — validates JWT, enqueues ARQ job, opens SSE stream
- `POST /api/agent/resume/{thread_id}` — resumes a paused graph after human approval
- `POST /api/agent/tool-result/{thread_id}` — receives local tool execution results from CLI, pushes to `tool_result:{call_id}` Redis key

`_relay_stream()` reads `sse:{thread_id}` with `XREAD BLOCK` and yields events. If the stream exists but has no new entries, it `continue`s (worker may be paused waiting for a local tool result).

### `api/routers/knowledge.py`
RAG knowledge base management (admin only):
- `POST /api/admin/knowledge` — upload document, chunk it, embed each chunk via OpenAI, store with clearance + department
- `GET /api/admin/knowledge` — list documents
- `DELETE /api/admin/knowledge/{doc_id}` — soft-delete

### `api/routers/admin/`

#### `api/routers/admin/__init__.py`
Assembles the combined admin router at prefix `/api/admin` from three sub-modules.

#### `api/routers/admin/_agents.py`
Agent definition CRUD + user bindings:
- `POST /api/admin/agents` — create agent definition
- `GET /api/admin/agents` — list all agents
- `GET /api/admin/agents/{name}` — get one agent
- `PATCH /api/admin/agents/{name}` — update prompt / tools / active status
- `DELETE /api/admin/agents/{name}` — delete agent
- `POST /api/admin/agents/{name}/bindings` — bind user to agent
- `GET /api/admin/users/{user_id}/agents` — list user's agents
- `DELETE /api/admin/bindings/{id}` — revoke binding
- `GET /api/admin/agents/{name}/bindings` — list bindings for agent

All mutations call `invalidate_graph_cache()`.

#### `api/routers/admin/_users.py`
User management:
- `GET /api/admin/users` — list all users with clearance info
- `POST /api/admin/users` — create user with hashed password
- `PATCH /api/admin/users/{user_id}` — update role, department, active state, or password

#### `api/routers/admin/_mcp.py`
MCP server registry:
- `POST /api/admin/mcp` — register external MCP server
- `GET /api/admin/mcp` — list all servers
- `PATCH /api/admin/mcp/{name}` — toggle active state
- `DELETE /api/admin/mcp/{name}` — remove server

---

## `graph/`

### `graph/state.py`
`AgentState` TypedDict — the single state object that flows through every graph node. Key fields:

| Field | Type | Description |
|---|---|---|
| `messages` | `list` | Full conversation history (LangChain messages) |
| `user_id` | `str` | Authenticated user |
| `user_role` | `str` | Role: viewer / analyst / manager / admin |
| `user_department` | `str` | Department name |
| `clearance_level` | `int` | Effective clearance (1–4) |
| `allowed_tools` | `list[str]` | Tools available to this user after RBAC intersection |
| `agent_definitions` | `list` | Available agents for this user (loaded by agent_resolver) |
| `current_agent` | `str` | Agent currently handling the task |
| `supervisor_intent` | `str` | Intent classified by supervisor |
| `tools_called` | `list[str]` | Accumulates tool names called this turn |
| `context` | `list[DataChunk]` | Optional context chunks (RAG) |
| `status` | `str` | `ok`, `permission_denied`, `done`, `error` |
| `done` | `bool` | True when supervisor decides to finish |

### `graph/state_builder.py`
`build_initial_state(thread_id, message, history, user_ctx, image)` — constructs the initial `AgentState` from request primitives. Used by both `main.py` (CLI) and `worker.py` (API mode) so construction logic is not duplicated.

### `graph/secure_graph.py`
Assembles and compiles the LangGraph graph. On first call, builds the 8-node security pipeline and wires all edges. Subsequent calls reuse the cached compiled graph unless `invalidate_graph_cache()` was called (triggered by admin mutations).

Key exports:
- `build_secure_graph()` — builds the graph
- `get_compiled_graph()` — returns cached or freshly built graph
- `invalidate_graph_cache()` — forces rebuild on next request

### `graph/supervisor.py`
The **only LLM call** in the security pipeline. Reads `state["agent_definitions"]` to know which agents are available, then asks the LLM to classify intent and select an agent.

Returns: `{"agent": "backend", "intent": "code_write", "confidence": 0.88}`

Guards:
- **Single-agent bypass** — if user has exactly 1 agent, skips LLM entirely
- **Loop detection** — same agent 3× in a row → force FINISH
- **Iteration cap** — `MAX_ITERATIONS` (default 8) → force FINISH
- **Low confidence fallback** — below `CONFIDENCE_THRESHOLD` → pick highest-confidence or FINISH

### `graph/agents/backend.py`
Specialist for code, APIs, refactoring, bug fixes. Creates a `create_react_agent` with tools filtered to `state["allowed_tools"]`. Reads the supervisor's goal from `state["supervisor_intent"]`.

### `graph/agents/devops.py`
Specialist for Docker, Compose, CI/CD, Linux, environment config.

### `graph/agents/qa.py`
Specialist for writing tests, analyzing logs, verification checklists.

### `graph/agents/dynamic.py`
`build_dynamic_agent_node(definition: AgentDefinition)` — factory that returns a node function for any DB-defined agent. Used by `secure_graph.py` to mount custom agents created via the admin API.

### `graph/agents/_utils.py`
Shared helpers for all agent nodes:
- `extract_tool_calls(messages)` — collects tool call names from message history
- `inject_tools_into_prompt(prompt, tools)` — appends available tool list to system prompt so the LLM knows what it can call

### `graph/nodes/rbac_guard.py`
**Layer 1.** Validates JWT (calls `decode_token()`) or reads plain `user_id/user_role/user_department` from state. Populates `state["allowed_tools"]` and `state["clearance_level"]`. Blocks if role is unknown.

### `graph/nodes/department_guard.py`
**Layer 2.** Takes the role's `allowed_tools` and intersects with `department.permitted_tools`. Caps `clearance_level` to `min(role_ceiling, dept_ceiling)`. This prevents cross-department tool escalation.

### `graph/nodes/agent_resolver.py`
**Layer 3.** Queries `UserAgentBinding` to find agents bound to the current user. Applies RBAC floor: `agent.allowed_tools ∩ user.allowed_tools`. Falls back to default agents if no bindings exist. Sets `state["agent_definitions"]` and `state["single_agent_mode"]`.

### `graph/nodes/data_classifier.py`
**Layer 4.** Iterates `state["context"]` (RAG chunks) and removes any chunks where `chunk.clearance_level > user.clearance_level`. Records stripped levels in `state["stripped_classifications"]`.

### `graph/nodes/intent_guard.py`
**Layer 5.** Keyword-scans the user message for write/execute patterns (`rm -rf`, `DROP TABLE`, `write_file`, etc.) **before** any LLM call. If the user's role doesn't have the relevant tool, sets `state["status"] = "permission_denied"` and ends the graph.

### `graph/nodes/prompt_injection_guard.py`
**Layer 6.** Regex-scans the message for 15+ injection patterns: instruction override (`ignore previous`, `forget instructions`), role hijack (`you are now`, `act as`), jailbreak (`DAN`, `developer mode`), delimiter injection, prompt leak (`repeat your instructions`). Blocks and ends graph on match.

### `graph/nodes/human_approval.py`
**Layer 7.** If `supervisor_intent` is `code_write` or `infrastructure_write`, calls LangGraph's `interrupt()` to pause the graph. The worker publishes `{"type": "approval_required"}` to the Redis Stream. The graph resumes via `POST /api/agent/resume/{thread_id}`.

### `graph/nodes/audit_log.py`
**Layer 8 (terminal).** After every turn, writes an `AuditRecord` to the DB: user, role, department, clearance, SHA-256 hash of query, tools used, data classification levels accessed, and final status. Records are append-only and never deleted.

---

## `tools/`

### `tools/__init__.py`
Master tool registry. Defines:
- `ALL_TOOLS` — list of all 17 LangChain tool objects
- `TOOL_MAP` — `{name: tool}` lookup dict
- `set_role_context(role, dept, clearance)` — sets ContextVars for `@permission_required`
- Re-exports `permission_required` decorator

### `tools/shell.py`
- `run_shell(command, timeout)` — executes bash commands via `_tool_client.call()` or local subprocess. Blocked commands list in `_safety.py`.
- `git_status()` — read-only `git status --short` + `git log --oneline -5`

### `tools/file_ops.py`
- `read_file(path)` — reads file content, classifies output clearance via `output_classifier`
- `write_file(path, content)` — writes file, path must be within workspace
- `edit_file(path, old, new)` — string replacement in file
- `list_files(directory)` — directory listing
- `search_code(query, directory)` — grep-like search with context lines
- `read_log(path, lines)` — tail of log file

All paths go through `_safety.py` allowlist check.

### `tools/code_exec.py`
- `execute_python(code, timeout)` — runs Python code via `_tool_client.call()` (tool-service or local)
- `run_tests(path, args)` — runs pytest, returns output
- `get_env(key)` — reads env var, truncates secrets (password/key/token patterns → first 4 chars + `***`)

### `tools/web_search.py`
- `web_search(query, max_results)` — DuckDuckGo search, returns top-N results as `{title, url, snippet}`. No API key needed.

### `tools/db_query.py`
- `query_db(sql)` — executes read-only SQL against the application database. Rejects anything that's not a `SELECT`. Caps at 200 rows. Returns results as formatted text.

### `tools/scraper.py`
- `scrape_page(url)` — fetches HTTP/HTTPS URL, converts HTML to clean text via BeautifulSoup, or returns raw JSON. Blocks cloud metadata endpoints (`169.254.169.254`, etc.) to prevent SSRF.

### `tools/secrets_scan.py`
- `scan_secrets(path)` — recursively scans files for hardcoded credentials. Pattern list covers AWS keys, GitHub tokens, RSA private keys, generic password/api_key variables. Returns matches with file:line.

### `tools/knowledge_search.py`
- `search_knowledge(query, top_k)` — vector search over `KnowledgeChunk` table using pgvector cosine similarity, filtered by `clearance_level ≤ user_clearance` and optional department. Falls back to SQL `LIKE` keyword search when pgvector extension is absent (SQLite / testing).

### `tools/rag_utils.py`
- `chunk_text(text, chunk_size, overlap)` — splits text into overlapping chunks. Prefers splitting at paragraph (`\n\n`) then sentence (`. `) boundaries to preserve semantic units. Default: 1200 chars, 200 overlap.

### `tools/mcp_loader.py`
- `load_mcp_tools()` — queries `MCPServer` table for active servers, connects via `langchain_mcp_adapters`, and returns LangChain tool objects. Runs in a background thread with a persistent event loop. Silently skips unreachable servers.

### `tools/_permission.py`
- `@permission_required` decorator — wraps tool functions. At execution time, reads role/dept from ContextVars (set by `set_role_context` in each agent node) and verifies the tool is in `role ∩ dept` allowed tools. Raises `PermissionError` if not.
- `_ROLE_CTX`, `_DEPT_CTX`, `_CLEARANCE_CTX` — ContextVars for per-request role state.

### `tools/_safety.py`
- `check_path(path)` — validates path is within workspace or allowed read dirs. Blocks `/etc`, `/proc`, `~/.ssh`, etc.
- `check_command(cmd)` — blocklist of destructive commands: `rm -rf /`, `mkfs`, `dd if=`, `:(){ :|:& }`, etc.
- `log_tool_call(tool, user, inputs_hash, output_class, duration_ms)` — writes to `tool_call_logs` table.

### `tools/_tool_client.py`
Routes dangerous tool calls based on configuration:
1. If `_local_exec_enabled()` → delegate to CLI via `_local_exec.execute()`
2. If `TOOL_SERVICE_URL` is set → HTTP POST to isolated tool-service container
3. Otherwise → run locally (dev mode, no isolation)

### `tools/_local_exec.py`
Redis round-trip for CLI tool delegation:
- `enable(thread_id)` — sets ContextVar, stores thread_id
- `is_enabled()` — checks ContextVar
- `execute(tool_name, inputs, workspace, timeout)`:
  1. `XADD sse:{thread_id}` with `type=tool_call_request`
  2. `BLPOP tool_result:{call_id}` (blocks up to `timeout + 30s`)
  3. Returns output string from CLI response

---

## `security/`

### `security/rbac.py`
DB-backed RBAC policies:
- `get_policy(role_name)` — returns `{allowed_tools, clearance_ceiling}` for a role
- `get_department_policy(dept_name)` — returns `{permitted_tools, clearance_ceiling}` for a dept
- `effective_tools(role, dept)` — `role.allowed_tools ∩ dept.permitted_tools`
- `effective_clearance(role, dept)` — `min(role_ceiling, dept_ceiling)`

### `security/classification.py`
- `ClearanceLevel` — IntEnum: `PUBLIC=1`, `INTERNAL=2`, `CONFIDENTIAL=3`, `SECRET=4`
- `DataChunk` — dataclass with `content`, `source`, `clearance_level`
- `filter_by_clearance(chunks, user_clearance)` — returns only chunks user can see

### `security/jwt_auth.py`
- `decode_token(token)` → `UserContext` — validates exp, extracts sub/role/dept/clearance
- `encode_token(user_id, role, dept, clearance)` → JWT string (HS256, 8h expiry)
- `make_dev_token(user_id, role, dept)` — convenience for local testing
- `UserContext` — dataclass: `user_id`, `role`, `department`, `clearance_level`, `allowed_tools`

### `security/password.py`
- `hash_password(plain)` → bcrypt hash string
- `verify_password(plain, hashed)` → bool

Uses `bcrypt` library directly (not passlib — passlib has a bcrypt>4 compatibility bug).

### `security/output_classifier.py`
Classifies tool output to determine its clearance level:
- **Path-based**: `.env` → CONFIDENTIAL, `.pem`/private key paths → SECRET, source files → INTERNAL
- **Content-based**: regex scans for private key headers, AWS key patterns, password= patterns
- `check_output_clearance(path, content, user_clearance)` — returns `(classification, should_redact)`

### `security/audit.py`
Singleton `AuditLogger`:
- `log(user_id, role, dept, clearance, query_hash, tools_used, classifications, status)` — appends to `audit_records` table
- Failures are silently swallowed (never raise from audit path)
- Records are append-only; no update or delete methods exposed

---

## `db/`

### `db/models.py`
All SQLAlchemy ORM models:

| Model | Purpose |
|---|---|
| `ClearanceLevel` | Lookup table: PUBLIC / INTERNAL / CONFIDENTIAL / SECRET |
| `Role` | viewer / analyst / manager / admin — clearance ceiling + JSON tool list |
| `Department` | engineering / devops / qa / data / security — clearance ceiling + JSON tool list |
| `User` | user_id, hashed_password, role FK, department FK, is_active |
| `AgentDefinition` | name, display_name, system_prompt, allowed_tools (JSON), department, is_active |
| `UserAgentBinding` | user_id → agent_name mapping, created_by, created_at |
| `KnowledgeChunk` | doc_id, filename, content, embedding (vector/text), clearance_level, department |
| `AuditRecord` | Immutable audit trail — user, role, dept, clearance, query_hash, tools, status |
| `ToolCallLog` | Per-tool-execution log — user, tool, inputs hash, output classification, duration |
| `MCPServer` | name, url, transport, description, is_active, created_by |

### `db/session.py`
- `get_engine()` — creates SQLAlchemy engine. Normalizes `postgres://` → `postgresql://`. Uses `psycopg2` for PostgreSQL, default dialect for SQLite. Configures connection pool.
- `get_db()` — context manager yielding a session with automatic commit on success / rollback on exception.

### `db/seed.py`
Idempotent seeder called by `init_db()`:
- 4 clearance levels
- 4 roles (viewer / analyst / manager / admin) with tool lists
- 7 departments (engineering / devops / qa / data / security / developer / all) with tool lists
- 4 default agent definitions (backend / devops / qa / developer)

Uses `INSERT OR IGNORE` / `filter_by(...).first()` patterns to be safe to call on every startup.

---

## `llm/`

### `llm/adapter.py`
`get_adapter()` — returns a LangChain chat model based on `LLM_PROVIDER` env var:
- `openai` → `ChatOpenAI(model=gpt-4o-mini)` (default)
- `openrouter` → `ChatOpenAI` with custom base URL
- `anthropic` → `ChatAnthropic`
- `ollama` → `ChatOllama`
- `vllm` → `ChatOpenAI` with vLLM base URL

### `llm/embeddings.py`
`get_embedder()` — returns `OpenAIEmbeddings(model=text-embedding-3-small)`. When `OPENAI_API_KEY` is absent, returns a stub that produces zero vectors (so the app starts without crashing in test environments).

---

## `tool_service/`

### `tool_service/main.py`
Isolated FastAPI service (runs in a Docker container with no internet access):
- `POST /execute` — accepts `{tool, inputs}` with Bearer auth (`TOOL_SERVICE_SECRET`)
- Routes to `executor.run_command()` or `executor.run_python()`
- `GET /healthz`

### `tool_service/executor.py`
Subprocess runners with OS-level resource limits:
- `run_command(cmd, timeout, workspace)` — spawns bash, applies RLIMIT_CPU / RLIMIT_AS / RLIMIT_FSIZE / RLIMIT_NPROC before exec
- `run_python(code, timeout)` — writes to tmpfile, spawns python3 with same limits
- Captures stdout + stderr, enforces timeout, returns `{stdout, stderr, exit_code}`

---

## `config/`

### `config/prompts.py`
System prompts for all agents. Each prompt includes:
- Agent identity and focus area
- Execution rules (act directly, don't explain what you'll do)
- Tool awareness (what's available)
- Output format expectations

Prompts: `SUPERVISOR_SYSTEM_PROMPT`, `BACKEND_SYSTEM_PROMPT`, `DEVOPS_SYSTEM_PROMPT`, `QA_SYSTEM_PROMPT`, `DEVELOPER_SYSTEM_PROMPT`

---

## `alembic/`

### `alembic/env.py`
Standard Alembic config. Auto-imports `Base.metadata` from `db/models.py`. Reads `DATABASE_URL` from environment.

### `alembic/versions/`

| File | What it adds |
|---|---|
| `0001_initial_schema.py` | All base tables: Role, Department, User, AuditRecord |
| `0002_add_new_tools.py` | query_db, scan_secrets, scrape_page tool permissions |
| `0003_add_knowledge.py` | KnowledgeChunk table + pgvector extension (`CREATE EXTENSION IF NOT EXISTS vector`) |
| `0004_add_agent_definitions.py` | AgentDefinition + UserAgentBinding tables |
| `0005_add_mcp_servers.py` | MCPServer table |

---

## `tests/`

### `tests/conftest.py`
pytest session setup:
- Sets `DATABASE_URL` to `sqlite:///:memory:` for isolation
- Calls `init_db()` once per session to seed RBAC data
- Yields and tears down SQLite after all tests

### `tests/test_rbac.py`
Policy tests: role clearance ceilings are monotonically increasing (viewer < analyst < manager < admin), tool sets grow with role, department policies are correct.

### `tests/test_permission.py`
`@permission_required` decorator tests: verifies that role ∩ dept intersection blocks correctly even when role has the tool but dept doesn't (and vice versa).

### `tests/test_prompt_injection.py`
27 parameterized injection patterns, all expected to be blocked by `prompt_injection_guard`. Also tests safe inputs that should pass.

### `tests/test_output_classifier.py`
Path-based classification (`.env` → CONFIDENTIAL, `.pem` → SECRET) and content-based detection (private key headers, AWS key patterns).

### `tests/test_intent_guard.py`
Intent guard blocks write/exec patterns for viewer/analyst, passes for manager/admin.

### `tests/test_department_guard.py`
Tool reduction: analyst in restricted dept loses tools. Clearance capping: analyst role (clearance 2) in PUBLIC dept (clearance 1) → effective clearance 1.

### `tests/test_supervisor_routing.py`
`parse_decision()` JSON parsing, loop detection (same agent 3×), iteration cap, fallback on low confidence.

### `tests/test_jwt_auth.py`
`encode_token` / `decode_token` roundtrip, expired token rejection, missing claims, wrong secret.

### `tests/test_agent_resolver.py`
User-specific agent bindings loaded, RBAC floor applied (agent tool list ∩ user tool list), default fallback when no bindings, `single_agent_mode=True` when user has exactly 1 agent.

### `tests/test_dynamic_agent.py`
`build_dynamic_agent_node()` factory: missing definition raises error, tool filtering works, supervisor goal injected into prompt.

### `tests/test_rag.py`
`chunk_text()` overlap, boundary detection. Embedding batch processing. Vector search and keyword fallback with clearance filter.

### `tests/test_tool_executor.py`
Tool Service executor: `run_command` and `run_python` with timeouts, exit codes, resource limit enforcement.

### `tests/test_tool_service_api.py`
Tool Service API: `/execute` requires Bearer auth, routes to correct executor, handles errors.

### `tests/test_tool_client.py`
`_tool_client.call()`: `is_enabled()` check, HTTP routing to tool-service, fallback when `TOOL_SERVICE_URL` not set.
