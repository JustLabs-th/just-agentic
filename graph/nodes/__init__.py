"""
Security & routing pipeline nodes.

These nodes run once per request BEFORE the supervisor LLM call.
They are all deterministic — no LLM involved.

Execution order (defined in graph/secure_graph.py):
  1. rbac_guard             — validate JWT/credentials, populate allowed_tools
  2. department_guard       — intersect role ∩ dept tools, cap clearance
  3. agent_resolver         — bind user to their allowed agents (from DB)
  4. data_classifier        — strip context chunks above user clearance
  5. intent_guard           — block dangerous keywords before LLM sees them
  6. prompt_injection_guard — block injection patterns before LLM sees them
  (then supervisor_node handles routing — defined in graph/supervisor.py)
  7. human_approval         — interrupt gate for write/exec actions
  8. audit_log              — append-only record after every turn
"""

from graph.nodes.rbac_guard import rbac_guard_node
from graph.nodes.department_guard import department_guard_node
from graph.nodes.data_classifier import data_classification_node
from graph.nodes.intent_guard import intent_guard_node
from graph.nodes.prompt_injection_guard import prompt_injection_guard_node
from graph.nodes.human_approval import human_approval_node
from graph.nodes.audit_log import audit_log_node

__all__ = [
    "rbac_guard_node",
    "department_guard_node",
    "data_classification_node",
    "intent_guard_node",
    "prompt_injection_guard_node",
    "human_approval_node",
    "audit_log_node",
]
