"""
MCP Tool Loader

Loads LangChain-compatible tools from external MCP servers.
Runs MCP client in a persistent background event loop so tools
remain usable from synchronous LangGraph nodes.

Requires: pip install langchain-mcp-adapters
"""

import asyncio
import logging
import threading
from typing import Optional

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# ── Background event loop (keeps MCP SSE connections alive) ───────────────────

_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_thread: Optional[threading.Thread] = None
_mcp_client = None           # langchain_mcp_adapters.MultiServerMCPClient
_cached_tools: list[BaseTool] = []
_lock = threading.Lock()


def _ensure_bg_loop() -> asyncio.AbstractEventLoop:
    global _bg_loop, _bg_thread
    if _bg_loop is not None and _bg_loop.is_running():
        return _bg_loop

    def _run():
        global _bg_loop
        _bg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_bg_loop)
        _bg_loop.run_forever()

    _bg_thread = threading.Thread(target=_run, daemon=True, name="mcp-loop")
    _bg_thread.start()
    # Wait until the loop is actually running
    import time
    for _ in range(100):
        if _bg_loop is not None and _bg_loop.is_running():
            break
        time.sleep(0.01)

    return _bg_loop


def _run_async(coro):
    """Submit a coroutine to the background loop and block until done."""
    loop = _ensure_bg_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=20)


# ── Server config from DB ─────────────────────────────────────────────────────

def _get_server_configs() -> dict:
    """Return {name: {url, transport}} for all active MCP servers."""
    try:
        from db.session import get_db
        from db.models import MCPServer
        with get_db() as db:
            servers = db.query(MCPServer).filter_by(is_active=True).all()
            return {
                s.name: {"url": s.url, "transport": s.transport}
                for s in servers
            }
    except Exception as exc:
        logger.debug("MCP: DB unavailable — %s", exc)
        return {}


# ── Async MCP client management ───────────────────────────────────────────────

async def _connect(configs: dict) -> list[BaseTool]:
    global _mcp_client
    from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore

    # Gracefully close existing client
    if _mcp_client is not None:
        try:
            await _mcp_client.__aexit__(None, None, None)
        except Exception:
            pass

    _mcp_client = MultiServerMCPClient(configs)
    await _mcp_client.__aenter__()
    return _mcp_client.get_tools()


# ── Public API ────────────────────────────────────────────────────────────────

def load_mcp_tools() -> list[BaseTool]:
    """Synchronously load tools from all active MCP servers.

    Returns an empty list (not an error) when:
    - No servers are configured
    - langchain-mcp-adapters is not installed
    - Any server is unreachable (warning logged)
    """
    with _lock:
        configs = _get_server_configs()
        if not configs:
            return []

        try:
            tools = _run_async(_connect(configs))
            logger.info("MCP: loaded %d tools from %s", len(tools), list(configs.keys()))
            return tools
        except ImportError:
            logger.debug("MCP: langchain-mcp-adapters not installed — skipping")
            return []
        except Exception as exc:
            logger.warning("MCP: failed to load tools — %s", exc)
            return []


def invalidate_mcp_cache() -> None:
    """Call after creating/updating/deleting an MCPServer to reload tools."""
    global _cached_tools
    with _lock:
        _cached_tools = []
