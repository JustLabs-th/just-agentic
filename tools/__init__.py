"""
Tools registry — single source of truth.

Usage in agents:
    from tools import ALL_TOOLS, TOOL_MAP, set_role_context

    set_role_context(state["user_role"])
    tools = [t for t in ALL_TOOLS if t.name in state["allowed_tools"]]
"""

from langchain_core.tools import BaseTool

from tools.shell import run_shell, git_status
from tools.file_ops import read_file, write_file, list_files, search_code, read_log
from tools.code_exec import execute_python, run_tests, get_env
from tools.web_search import web_search
from tools.db_query import query_db
from tools.secrets_scan import scan_secrets
from tools.scraper import scrape_page
from tools.knowledge_search import search_knowledge
from tools._permission import set_role_context, get_role_context, permission_required


# ── Master tool list ───────────────────────────────────────────────────────

ALL_TOOLS: list[BaseTool] = [
    # File operations
    read_file,
    write_file,
    list_files,
    search_code,
    read_log,
    # Shell / git
    run_shell,
    git_status,
    # Code execution
    execute_python,
    run_tests,
    get_env,
    # Web
    web_search,
    scrape_page,
    # Database
    query_db,
    # Security
    scan_secrets,
    # Knowledge base (RAG)
    search_knowledge,
]

TOOL_MAP: dict[str, BaseTool] = {t.name: t for t in ALL_TOOLS}
