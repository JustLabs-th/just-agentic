"""
Specialist agent nodes — called by the supervisor after security checks pass.

Each agent wraps create_react_agent() with:
  - A system prompt (from config/prompts.py or DB for dynamic agents)
  - A tool list filtered by state["allowed_tools"] (RBAC intersection)
  - ReAct loop: reason → call tool → observe → repeat → final answer

Agents available:
  backend_node  — application code, APIs, bug fixes, refactoring
  devops_node   — Docker, CI/CD, infrastructure, environment
  qa_node       — test execution, log analysis, validation

Dynamic agents (loaded from DB at runtime) are created by graph/agents/dynamic.py
and registered into the graph by graph/secure_graph.py on each build.
"""

from graph.agents.backend import backend_node
from graph.agents.devops import devops_node
from graph.agents.qa import qa_node

__all__ = ["backend_node", "devops_node", "qa_node"]
