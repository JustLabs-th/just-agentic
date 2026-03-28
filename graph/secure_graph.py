"""
Secure Multi-Agent Graph

Flow:
  START
    → rbac_guard               (validate JWT / plain credentials, populate allowed_tools)
    → department_guard         (intersect role ∩ dept tools, cap clearance)
    → agent_resolver           (load user's allowed agents from DB, enforce RBAC floor)
    → data_classifier          (strip context above clearance level)
    → intent_guard             (deterministic write/exec keyword block)
    → prompt_injection_guard   (regex injection scan)
    → supervisor               (LLM routing: plan + route to specialist agent)
    → human_approval           (interrupt for dangerous actions)
    ↙            ↓           ↘
  backend      devops    <custom agents>
    ↘            ↓           ↙
    → supervisor               (review result → route next or finish)
    → audit_log                (write immutable record)
  END

Defense in Depth (8 layers):
  Layer 1 — rbac_guard:              blocks unknown roles / invalid JWT
  Layer 2 — department_guard:        intersects role ∩ dept, caps clearance ceiling
  Layer 3 — agent_resolver:          binds users to specific agents, RBAC floor on tools
  Layer 4 — data_classifier:         strips data chunks above user clearance
  Layer 5 — intent_guard:            keyword-blocks write/exec intents pre-LLM
  Layer 6 — prompt_injection_guard:  regex-blocks injection patterns pre-LLM
  Layer 7 — human_approval:          interrupt gate for code_write / infra_write
  Layer 8 — @permission_required:    tool-level re-check at execution time
"""

import os
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState
from graph.nodes.rbac_guard import rbac_guard_node
from graph.nodes.department_guard import department_guard_node
from graph.nodes.agent_resolver import agent_resolver_node
from graph.nodes.data_classifier import data_classification_node
from graph.nodes.intent_guard import intent_guard_node
from graph.nodes.prompt_injection_guard import prompt_injection_guard_node
from graph.nodes.human_approval import human_approval_node
from graph.nodes.audit_log import audit_log_node
from graph.supervisor import supervisor_node
from graph.agents.backend import backend_node
from graph.agents.devops import devops_node
from graph.agents.qa import qa_node
from graph.agents.dynamic import dynamic_agent_node

MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "8"))

# Cached compiled graph — invalidated when agent definitions change
_graph = None


def invalidate_graph_cache() -> None:
    """Call this after creating/updating/deleting an AgentDefinition."""
    global _graph
    _graph = None


def get_or_build_graph():
    """Return cached graph or rebuild it from current DB state."""
    global _graph
    if _graph is None:
        _graph = build_secure_graph()
    return _graph


# ---------------------------------------------------------------------------
# Entry routing — after RBAC check
# ---------------------------------------------------------------------------

def route_after_rbac(state: AgentState) -> str:
    if state.get("status") == "permission_denied":
        return "audit_log"
    return "department_guard"


def route_after_dept(state: AgentState) -> str:
    if state.get("status") == "permission_denied":
        return "audit_log"
    return "agent_resolver"


def route_after_resolver(state: AgentState) -> str:
    if state.get("status") == "permission_denied":
        return "audit_log"
    return "data_classifier"


# ---------------------------------------------------------------------------
# Exit routing — supervisor decides done or routes to agent
# ---------------------------------------------------------------------------

def route_from_supervisor(state: AgentState) -> str:
    status = state.get("status", "working")

    if status in ("done", "error", "permission_denied"):
        return "audit_log"
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return "audit_log"

    current = state.get("current_agent", "")
    allowed = set(state.get("allowed_agents") or [])
    if current in allowed:
        return "human_approval"

    return "audit_log"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _load_agent_names() -> list[str]:
    """Load all active agent names from DB. Returns defaults if DB unavailable."""
    try:
        from db.models import AgentDefinition
        from db.session import get_db
        with get_db() as db:
            return [
                a.name for a in
                db.query(AgentDefinition).filter_by(is_active=True).all()
            ]
    except Exception:
        return ["backend", "devops", "qa"]


def build_secure_graph():
    agent_names = _load_agent_names()

    # Ensure at minimum the three default agents exist as names
    for default in ("backend", "devops", "qa"):
        if default not in agent_names:
            agent_names.append(default)

    graph = StateGraph(AgentState)

    # Security entry nodes (run once per request)
    graph.add_node("rbac_guard",             rbac_guard_node)
    graph.add_node("department_guard",       department_guard_node)
    graph.add_node("agent_resolver",         agent_resolver_node)
    graph.add_node("data_classifier",        data_classification_node)
    graph.add_node("intent_guard",           intent_guard_node)
    graph.add_node("prompt_injection_guard", prompt_injection_guard_node)

    # Multi-agent orchestration
    graph.add_node("supervisor",     supervisor_node)
    graph.add_node("human_approval", human_approval_node)

    # Register hardcoded agents (backward-compatible)
    graph.add_node("backend", backend_node)
    graph.add_node("devops",  devops_node)
    graph.add_node("qa",      qa_node)

    # Register dynamic custom agents (skip the three already registered above)
    for name in agent_names:
        if name not in ("backend", "devops", "qa"):
            graph.add_node(name, dynamic_agent_node(name))

    # Audit exit node
    graph.add_node("audit_log", audit_log_node)

    # ── Entry ──
    graph.set_entry_point("rbac_guard")

    # ── RBAC → dept_guard or block ──
    graph.add_conditional_edges(
        "rbac_guard",
        route_after_rbac,
        {"department_guard": "department_guard", "audit_log": "audit_log"},
    )

    # ── Dept guard → agent_resolver or block ──
    graph.add_conditional_edges(
        "department_guard",
        route_after_dept,
        {"agent_resolver": "agent_resolver", "audit_log": "audit_log"},
    )

    # ── Agent resolver → data_classifier or block ──
    graph.add_conditional_edges(
        "agent_resolver",
        route_after_resolver,
        {"data_classifier": "data_classifier", "audit_log": "audit_log"},
    )

    # ── Classifier → intent_guard → injection_guard → supervisor ──
    graph.add_edge("data_classifier", "intent_guard")
    graph.add_conditional_edges(
        "intent_guard",
        lambda s: "audit_log" if s.get("status") == "permission_denied" else "prompt_injection_guard",
        {"prompt_injection_guard": "prompt_injection_guard", "audit_log": "audit_log"},
    )
    graph.add_conditional_edges(
        "prompt_injection_guard",
        lambda s: "audit_log" if s.get("status") == "permission_denied" else "supervisor",
        {"supervisor": "supervisor", "audit_log": "audit_log"},
    )

    # ── Supervisor → human_approval (except done) ──
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {"human_approval": "human_approval", "audit_log": "audit_log"},
    )

    # ── human_approval → agent or audit_log (if rejected) ──
    approval_targets = {name: name for name in agent_names}
    approval_targets["audit_log"] = "audit_log"
    graph.add_conditional_edges(
        "human_approval",
        lambda s: "audit_log" if s.get("status") == "permission_denied"
                  else s.get("current_agent", "audit_log"),
        approval_targets,
    )

    # ── All agents loop back to supervisor ──
    for name in agent_names:
        graph.add_edge(name, "supervisor")

    # ── Audit → END ──
    graph.add_edge("audit_log", END)

    checkpointer = _make_checkpointer()
    return graph.compile(checkpointer=checkpointer)


def _make_checkpointer():
    """Use PostgresSaver when DATABASE_URL is set, else fall back to MemorySaver."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return MemorySaver()

    conn_url = db_url
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if conn_url.startswith(prefix):
            conn_url = conn_url.replace(prefix, "postgresql://", 1)
            break

    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.connect(conn_url, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver
