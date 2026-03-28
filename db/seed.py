"""Seed default RBAC data on first startup. Idempotent — safe to call repeatedly."""

from db.models import ClearanceLevel, Role, Department, AgentDefinition
from db.session import get_db

# ── Tool sets ──────────────────────────────────────────────────────────────────

_READ_TOOLS: list[str] = [
    "read_file", "list_files", "search_code", "read_log",
    "git_status", "get_env", "web_search",
]

# analyst adds reconnaissance + reporting tools
_ANALYST_TOOLS: list[str] = _READ_TOOLS + ["scan_secrets", "scrape_page"]

# manager adds execution + DB inspection
_ANALYZE_TOOLS: list[str] = _ANALYST_TOOLS + [
    "run_shell", "execute_python", "run_tests", "query_db",
]

# admin adds file write
_WRITE_TOOLS: list[str] = _ANALYZE_TOOLS + ["write_file"]

# ── Default seed data ──────────────────────────────────────────────────────────

_DEFAULT_CLEARANCE_LEVELS = [
    {"name": "PUBLIC",       "level_order": 1},
    {"name": "INTERNAL",     "level_order": 2},
    {"name": "CONFIDENTIAL", "level_order": 3},
    {"name": "SECRET",       "level_order": 4},
]

_DEFAULT_ROLES = [
    {"name": "viewer",  "clearance_ceiling": "PUBLIC",       "allowed_tools": ["read_file", "list_files", "web_search"]},
    {"name": "analyst", "clearance_ceiling": "INTERNAL",     "allowed_tools": _ANALYST_TOOLS},
    {"name": "manager", "clearance_ceiling": "CONFIDENTIAL", "allowed_tools": _ANALYZE_TOOLS},
    {"name": "admin",   "clearance_ceiling": "SECRET",       "allowed_tools": _WRITE_TOOLS},
]

_DEFAULT_DEPARTMENTS = [
    {
        "name": "engineering", "max_clearance": "CONFIDENTIAL",
        "permitted_tools": [
            "read_file", "write_file", "list_files", "search_code",
            "run_shell", "git_status", "execute_python", "run_tests",
            "web_search", "scrape_page", "scan_secrets", "query_db",
        ],
    },
    {
        "name": "devops", "max_clearance": "CONFIDENTIAL",
        "permitted_tools": [
            "read_file", "write_file", "list_files", "read_log",
            "run_shell", "git_status", "get_env", "web_search",
            "scrape_page", "query_db",
        ],
    },
    {
        "name": "qa", "max_clearance": "INTERNAL",
        "permitted_tools": [
            "read_file", "list_files", "search_code", "read_log",
            "run_shell", "run_tests", "execute_python", "web_search",
            "scrape_page", "scan_secrets",
        ],
    },
    {
        "name": "data", "max_clearance": "SECRET",
        "permitted_tools": [
            "read_file", "list_files", "search_code", "read_log",
            "execute_python", "web_search", "scrape_page", "query_db",
        ],
    },
    {
        "name": "security", "max_clearance": "SECRET",
        "permitted_tools": _WRITE_TOOLS,
    },
    {
        "name": "all", "max_clearance": "SECRET",
        "permitted_tools": _WRITE_TOOLS,
    },
]


_DEFAULT_AGENTS = [
    {
        "name": "backend",
        "display_name": "Backend Agent",
        "system_prompt": "You are the Backend Agent.\n\nFocus: application code, APIs, business logic, bug fixing, refactoring, source files.\n\nExecution rules:\n- Execute the task immediately and directly. Do NOT present options or ask for confirmation.\n- Use tools to inspect before changing. Read the file first if you need context.\n- Use write_file to save any code you produce.\n- Prefer minimal, safe changes.\n- Explain root cause briefly after completing the fix.",
        "allowed_tools": [
            "read_file", "write_file", "list_files", "search_code",
            "run_shell", "git_status", "execute_python", "run_tests",
            "web_search", "scrape_page", "scan_secrets", "query_db",
        ],
        "department": "engineering",
    },
    {
        "name": "devops",
        "display_name": "DevOps Agent",
        "system_prompt": "You are the DevOps Agent.\n\nFocus: Docker, docker-compose, environment variables, Linux, CI/CD, deployment scripts.\n\nExecution rules:\n- Execute the task immediately and directly. Do NOT present options or ask for confirmation.\n- When asked to create a file (Dockerfile, docker-compose.yml, .env, etc.) — write it using write_file right away.\n- Inspect existing config files first if relevant.\n- Avoid destructive shell commands unless explicitly approved.\n- Warn about security pitfalls (secrets in images, etc.) after completing the task.",
        "allowed_tools": [
            "read_file", "write_file", "list_files", "read_log",
            "run_shell", "git_status", "get_env", "web_search",
            "scrape_page", "query_db",
        ],
        "department": "devops",
    },
    {
        "name": "qa",
        "display_name": "QA Agent",
        "system_prompt": "You are the QA Agent.\n\nFocus: test execution, log inspection, reproduction steps, validation, acceptance checklists.\n\nExecution rules:\n- Execute the task immediately and directly. Do NOT present options or ask for confirmation.\n- Run tests and show full output. Do not summarize without running first.\n- Summarize failures in plain language: what failed, why, what to fix.\n- Propose the exact next verification step.",
        "allowed_tools": [
            "read_file", "list_files", "search_code", "read_log",
            "run_shell", "run_tests", "execute_python", "web_search",
            "scrape_page", "scan_secrets",
        ],
        "department": "qa",
    },
]


def seed_default_agents() -> None:
    """Seed backend/devops/qa as default agent definitions if not present."""
    with get_db() as db:
        if db.query(AgentDefinition).filter_by(is_default=True).count() == 0:
            for a in _DEFAULT_AGENTS:
                db.add(AgentDefinition(
                    name=a["name"],
                    display_name=a["display_name"],
                    system_prompt=a["system_prompt"],
                    allowed_tools=a["allowed_tools"],
                    department=a["department"],
                    is_default=True,
                    is_active=True,
                    created_by="system",
                ))


def seed_defaults() -> None:
    """Insert default RBAC data if tables are empty."""
    with get_db() as db:
        # ── Clearance levels ──
        if db.query(ClearanceLevel).count() == 0:
            for data in _DEFAULT_CLEARANCE_LEVELS:
                db.add(ClearanceLevel(**data))
            db.flush()

        level_map: dict[str, ClearanceLevel] = {
            cl.name: cl for cl in db.query(ClearanceLevel).all()
        }

        # ── Roles ──
        if db.query(Role).count() == 0:
            for r in _DEFAULT_ROLES:
                db.add(Role(
                    name=r["name"],
                    clearance_ceiling_id=level_map[r["clearance_ceiling"]].id,
                    allowed_tools=r["allowed_tools"],
                ))

        # ── Departments ──
        if db.query(Department).count() == 0:
            for d in _DEFAULT_DEPARTMENTS:
                db.add(Department(
                    name=d["name"],
                    max_clearance_id=level_map[d["max_clearance"]].id,
                    permitted_tools=d["permitted_tools"],
                ))

    seed_default_agents()
