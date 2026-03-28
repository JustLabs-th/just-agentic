"""
Secure Multi-Agent Graph

Flow:
  START
    → rbac_guard               (validate JWT / plain credentials, populate allowed_tools)
    → department_guard         (intersect role ∩ dept tools, cap clearance)
    → data_classifier          (strip context above clearance level)
    → intent_guard             (deterministic write/exec keyword block)
    → prompt_injection_guard   (regex injection scan)
    → supervisor               (LLM routing: plan + route to specialist agent)
    → human_approval           (interrupt for dangerous actions)
    ↙            ↓           ↘
  backend      devops         qa
    ↘            ↓           ↙
    → supervisor               (review result → route next or finish)
    → audit_log                (write immutable JSONL record)
  END

Defense in Depth (7 layers):
  Layer 1 — rbac_guard:              blocks unknown roles / invalid JWT
  Layer 2 — department_guard:        intersects role ∩ dept, caps clearance ceiling
  Layer 3 — data_classifier:         strips data chunks above user clearance
  Layer 4 — intent_guard:            keyword-blocks write/exec intents pre-LLM
  Layer 5 — prompt_injection_guard:  regex-blocks injection patterns pre-LLM
  Layer 6 — human_approval:          interrupt gate for code_write / infra_write
  Layer 7 — @permission_required:    tool-level re-check at execution time
"""

import os
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState
from graph.nodes.rbac_guard import rbac_guard_node
from graph.nodes.department_guard import department_guard_node
from graph.nodes.data_classifier import data_classification_node
from graph.nodes.intent_guard import intent_guard_node
from graph.nodes.prompt_injection_guard import prompt_injection_guard_node
from graph.nodes.human_approval import human_approval_node
from graph.nodes.audit_log import audit_log_node
from graph.supervisor import supervisor_node
from graph.agents.backend import backend_node
from graph.agents.devops import devops_node
from graph.agents.qa import qa_node

MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "8"))


# ---------------------------------------------------------------------------
# Entry routing — after RBAC check
# ---------------------------------------------------------------------------

def route_after_rbac(state: AgentState) -> str:
    if state.get("status") == "permission_denied":
        return "audit_log"
    return "department_guard"


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
    if current in ("backend", "devops", "qa"):
        return "human_approval"   # always pass through approval gate

    return "audit_log"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_secure_graph():
    graph = StateGraph(AgentState)

    # Security entry nodes (run once)
    graph.add_node("rbac_guard",        rbac_guard_node)
    graph.add_node("department_guard",  department_guard_node)
    graph.add_node("data_classifier",   data_classification_node)
    graph.add_node("intent_guard",           intent_guard_node)
    graph.add_node("prompt_injection_guard", prompt_injection_guard_node)

    # Multi-agent nodes
    graph.add_node("supervisor",      supervisor_node)
    graph.add_node("human_approval",  human_approval_node)
    graph.add_node("backend",         backend_node)
    graph.add_node("devops",          devops_node)
    graph.add_node("qa",              qa_node)

    # Audit exit node (run once)
    graph.add_node("audit_log",       audit_log_node)

    # ── Entry ──
    graph.set_entry_point("rbac_guard")

    # ── RBAC → dept_guard or block ──
    graph.add_conditional_edges(
        "rbac_guard",
        route_after_rbac,
        {"department_guard": "department_guard", "audit_log": "audit_log"},
    )

    # ── Dept guard → classifier or block ──
    graph.add_conditional_edges(
        "department_guard",
        lambda s: "audit_log" if s.get("status") == "permission_denied" else "data_classifier",
        {"data_classifier": "data_classifier", "audit_log": "audit_log"},
    )

    # ── Classifier → intent_guard → supervisor ──
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

    # ── Supervisor → human_approval (always, except done) ──
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "human_approval": "human_approval",
            "audit_log":      "audit_log",
        },
    )

    # ── human_approval → agent or audit_log (if rejected) ──
    graph.add_conditional_edges(
        "human_approval",
        lambda s: "audit_log" if s.get("status") == "permission_denied"
                  else s.get("current_agent", "audit_log"),
        {"backend": "backend", "devops": "devops", "qa": "qa", "audit_log": "audit_log"},
    )

    # ── Agents loop back to supervisor ──
    graph.add_edge("backend", "supervisor")
    graph.add_edge("devops",  "supervisor")
    graph.add_edge("qa",      "supervisor")

    # ── Audit → END ──
    graph.add_edge("audit_log", END)

    checkpointer = _make_checkpointer()
    return graph.compile(checkpointer=checkpointer)


def _make_checkpointer():
    """Use PostgresSaver when DATABASE_URL is set, else fall back to MemorySaver."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return MemorySaver()

    # Normalize URL for psycopg (psycopg3 uses plain postgresql://)
    conn_url = db_url
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if conn_url.startswith(prefix):
            conn_url = conn_url.replace(prefix, "postgresql://", 1)
            break

    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.connect(conn_url)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver
