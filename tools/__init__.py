"""
Tools package — registry and internal infrastructure.

Public API (used by agents and graph):
  ALL_TOOLS         list[BaseTool]        all registered LangChain tools
  TOOL_MAP          dict[str, BaseTool]   tool lookup by name
  set_role_context  (role: str) → None    set ContextVar before tool execution
  permission_required                     decorator — enforces RBAC at call time

Usage in agents:
    from tools import ALL_TOOLS, TOOL_MAP, set_role_context
    set_role_context(state["user_role"])
    tools = [t for t in ALL_TOOLS if t.name in state["allowed_tools"]]

─── Registered tools (17) ─────────────────────────────────────────────────────
  File ops  : read_file, write_file, edit_file, list_files, search_code, read_log
  Shell     : run_shell, git_status
  Code      : execute_python, run_tests, get_env
  Web       : web_search, scrape_page
  Database  : query_db
  Security  : scan_secrets
  Knowledge : search_knowledge

─── Internal modules (NOT registered tools) ────────────────────────────────────
  _permission.py    @permission_required decorator + role/thread ContextVars
  _safety.py        path allowlist, command blocklist, tool call logger
  _tool_client.py   HTTP routing → isolated tool-service container (Docker/prod)
  _local_exec.py    Redis round-trip → CLI client exec (local_exec mode)
  mcp_loader.py     MCP server loader — background event loop, not a tool
  rag_utils.py      text chunker for RAG ingestion (used by api/routers/knowledge.py)
"""

from langchain_core.tools import BaseTool

from tools.shell import run_shell, git_status
from tools.file_ops import read_file, write_file, edit_file, list_files, search_code, read_log
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
    edit_file,
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
