# just-agentic

Secure multi-agent system using LangGraph + OpenAI. Supervisor routes tasks to specialist agents with RBAC, department-based access control, data classification, prompt injection detection, human approval for dangerous actions, and RAG knowledge base.

Runs as a **CLI** or **FastAPI + SSE API** (with Next.js frontend).

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY, DATABASE_URL
python main.py          # CLI mode
uvicorn api.main:app    # API mode
```

## Graph Flow

```
rbac_guard → department_guard → agent_resolver → data_classifier → intent_guard → prompt_injection_guard
  → supervisor → human_approval → [backend | devops | qa | <custom>] → supervisor → audit_log
```

- **Agents**: hardcoded defaults (`backend`, `devops`, `qa`) + custom agents created by super-admin
- **Supervisor**: routes by intent + confidence score, with fallback, retry, loop detection; single-agent bypass when user has only one agent
- **Human approval**: `interrupt()` before `code_write` / `infrastructure_write` actions
- **Checkpoint**: PostgresSaver (PostgreSQL) or MemorySaver (fallback/testing)

## Defense in Depth (8 Layers)

| Layer | Node / Component | What it blocks |
|---|---|---|
| 1 | `rbac_guard` | Unknown role / invalid JWT |
| 2 | `department_guard` | Intersects role ∩ dept tools, caps clearance |
| 3 | `agent_resolver` | Binds users to agents, enforces RBAC floor on agent tools |
| 4 | `data_classifier` | Strips context chunks above user clearance |
| 5 | `intent_guard` | Keyword-blocks write/exec pre-LLM |
| 6 | `prompt_injection_guard` | Regex-blocks injection patterns pre-LLM |
| 7 | `human_approval` | interrupt() gate for dangerous actions |
| 8 | `@permission_required` | Tool-level last resort at execution time |

## Auth Modes

```
[1] JWT token  — paste Bearer token; role/dept/clearance decoded from token
[2] Dev mode   — enter user_id / role / department manually
```

Set `JWT_SECRET` in `.env` to enable JWT mode. Generate a dev token:

```python
from security.jwt_auth import make_dev_token
print(make_dev_token("alice", "analyst", "engineering"))
```

## Key Files

| File | Purpose |
|---|---|
| `main.py` | CLI entry — init_db, login, stream, interrupt handling |
| `api/main.py` | FastAPI app — startup, CORS, routers |
| `api/routers/agent.py` | POST /api/agent/chat + /resume — SSE streaming |
| `api/routers/auth.py` | POST /api/auth/login — JWT + dev modes |
| `api/routers/admin.py` | CRUD agent definitions + user–agent bindings |
| `api/routers/knowledge.py` | Upload/list/delete knowledge documents (RAG) |
| `graph/secure_graph.py` | Graph definition — loads agents from DB at startup |
| `graph/supervisor.py` | Routing + intent/confidence + single-agent bypass |
| `graph/nodes/agent_resolver.py` | Loads user's allowed agents from DB, enforces RBAC floor |
| `graph/agents/dynamic.py` | Runtime agent factory from DB definition |
| `graph/state.py` | `AgentState` TypedDict — single unified state |
| `db/models.py` | SQLAlchemy ORM — all models including AgentDefinition, KnowledgeChunk |
| `db/seed.py` | Default RBAC + agent definitions seeding |
| `security/rbac.py` | DB-backed roles, departments, effective tools + clearance |
| `security/jwt_auth.py` | JWT decode/encode (PyJWT, HS256) |
| `security/output_classifier.py` | Classifies tool output by path + content |
| `llm/adapter.py` | LLM provider switch |
| `llm/embeddings.py` | OpenAI text-embedding-3-small adapter |
| `tools/knowledge_search.py` | RAG search tool — pgvector + keyword fallback |
| `tools/rag_utils.py` | Text chunker (paragraph-aware, overlapping) |
| `config/prompts.py` | System prompts for all agents |

## Roles & Departments

| Role | Clearance | Tools |
|---|---|---|
| viewer | PUBLIC (1) | read_file, list_files, web_search |
| analyst | INTERNAL (2) | + search_code, git_status, read_log, query_db, scrape_page, scan_secrets, search_knowledge |
| manager | CONFIDENTIAL (3) | + run_shell, run_tests, get_env, execute_python |
| admin | SECRET (4) | all tools including write_file |

Effective access = `role.allowed_tools ∩ dept.permitted_tools`, clearance = `min(role, dept)`.

## ABAC — Dynamic Agent Management

Super-admins (admin role) can create custom agent definitions and bind them to users:

```
POST /api/admin/agents                    — create agent definition
PATCH /api/admin/agents/{name}            — update (prompt, tools, active status)
POST /api/admin/agents/{name}/bindings    — bind user to agent
GET  /api/admin/users/{user_id}/agents    — list user's agents
DELETE /api/admin/bindings/{id}           — revoke binding
```

- RBAC is the hard floor: agent tools = `agent.allowed_tools ∩ user.effective_rbac_tools`
- Users with no bindings fall back to default agents (backend/devops/qa)
- Users with exactly 1 agent skip supervisor LLM routing entirely

## RAG Knowledge Base

Admins upload documents → chunked → embedded → stored with clearance level:

```
POST   /api/admin/knowledge              — upload + chunk + embed
GET    /api/admin/knowledge              — list documents
DELETE /api/admin/knowledge/{doc_id}     — soft-delete
```

Agents use `search_knowledge(query)` tool:
- Vector search via pgvector (cosine similarity)
- Keyword fallback when pgvector unavailable (SQLite / testing)
- Results filtered by `clearance_level ≤ user_clearance` and department

**Production:** requires `pip install pgvector` and PostgreSQL with `vector` extension.

## Database

`init_db()` runs at startup — creates tables and seeds default RBAC + agent data.

```
db/
  models.py     ORM: ClearanceLevel, Role, Department, User,
                     AgentDefinition, UserAgentBinding,
                     KnowledgeChunk, AuditRecord, ToolCallLog
  session.py    Engine factory — PostgreSQL (prod) / SQLite (test)
  seed.py       Idempotent default data seeding
```

Migrations via Alembic:

```bash
alembic upgrade head
```

## Environment

```bash
LLM_PROVIDER=openai          # openai | openrouter | anthropic | ollama | vllm
OPENAI_API_KEY=sk-...
JWT_SECRET=your-secret-here
DATABASE_URL=postgresql://user:pass@localhost:5432/just_agentic
MAX_ITERATIONS=8
CONFIDENCE_THRESHOLD=0.55
WORKSPACE_ROOT=/path/to/project
CHECKPOINT_BACKEND=postgres  # postgres | memory
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | JWT or dev login → returns access token |
| POST | `/api/agent/chat` | Start task — streams SSE events |
| POST | `/api/agent/resume/{thread_id}` | Resume after human approval interrupt |
| POST | `/api/admin/agents` | Create agent definition (admin) |
| POST | `/api/admin/agents/{name}/bindings` | Bind user to agent (admin) |
| POST | `/api/admin/knowledge` | Upload knowledge document (admin) |
| GET | `/healthz` | Health check |

SSE event types: `thread_id`, `agent_switch`, `message`, `approval_required`, `permission_denied`, `done`, `error`

## Tests

```bash
python -m pytest tests/ -v   # 191 tests
```

## Docs

- [Architecture & module map](docs/architecture.md)
- [RBAC & data classification](docs/rbac.md)
- [Supervisor routing logic](docs/supervisor.md)
- [Tools & safety layer](docs/tools.md)
- [LLM providers](docs/llm-providers.md)

## Conventions

- State is immutable per node — always return `{**state, ...updated_fields}`
- Security is enforced in code (not prompt) — LLM is never trusted to enforce permissions
- Tools are filtered by `state.allowed_tools` before binding to any agent
- RBAC is always the floor — no layer can grant tools beyond `role ∩ dept`
- Every action is logged to `audit_records` table (append-only, never deleted)
- `init_db()` is idempotent — safe to call on every startup
- Graph is rebuilt from DB when agent definitions change (`invalidate_graph_cache()`)
