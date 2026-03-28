"""Seed default RBAC data on first startup. Idempotent — safe to call repeatedly."""

from db.models import ClearanceLevel, Role, Department
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
