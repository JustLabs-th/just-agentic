"""
Graph package — LangGraph multi-agent pipeline.

Key exports:
  build_secure_graph()    — compile + cache the full 8-layer security graph
  invalidate_graph_cache()— force rebuild on next call (after agent DB changes)
  AgentState              — TypedDict for the single shared state object

Entry points:
  main.py         uses build_secure_graph() directly (CLI mode)
  worker.py       uses build_secure_graph() inside the ARQ worker process
  api/routers/admin.py calls invalidate_graph_cache() after DB mutations
"""

from graph.secure_graph import build_secure_graph, invalidate_graph_cache
from graph.state import AgentState

__all__ = ["build_secure_graph", "invalidate_graph_cache", "AgentState"]
