from typing import Annotated, TypedDict, List, Dict, Any, Optional
from langgraph.graph.message import add_messages
from security.classification import DataChunk


class AgentState(TypedDict, total=False):
    # ── LangGraph message history ──────────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── Identity & RBAC (set at entry, never modified by agents) ──────────
    jwt_token: str                # Bearer token — if set, rbac_guard validates it
    user_id: str
    user_role: str
    user_department: str          # engineering | devops | qa | data | security | all
    clearance_level: int          # effective = min(role, dept) ceiling
    allowed_tools: list[str]      # effective = role.allowed ∩ dept.permitted

    # ── Data classification ────────────────────────────────────────────────
    context: list[DataChunk]           # raw context passed in by caller
    visible_context: list[DataChunk]   # after clearance filter
    stripped_levels: list[int]         # classification levels removed
    data_classifications_accessed: list[int]

    # ── Multi-agent routing ────────────────────────────────────────────────
    # ── ABAC — resolved by agent_resolver, consumed by supervisor ─────────────────
    allowed_agents: list[str]          # agent names the user is bound to
    agent_definitions: list[dict]      # [{name, display_name, system_prompt, allowed_tools}]
    single_agent_mode: bool            # True when len(allowed_agents) == 1

    user_goal: str
    current_agent: str            # supervisor | backend | devops | qa | <custom>
    plan: list[str]
    goal_for_agent: str           # supervisor → agent instruction per turn
    working_memory: dict[str, Any]

    # ── Execution tracking ─────────────────────────────────────────────────
    tools_called: list[str]
    iteration: int

    # ── Supervisor decision metadata ───────────────────────────────────────
    intent: str                   # classified intent from supervisor
    confidence: float             # 0.0–1.0 supervisor confidence in routing
    routing_history: list[str]    # per-turn agent names — for loop detection
    retry_count: dict[str, int]   # {agent: n_retries} per task
    supervisor_log: list[dict]    # structured log of every routing decision

    # ── Output ────────────────────────────────────────────────────────────
    final_answer: str
    status: str                   # planning | working | done | error | permission_denied
    error: str

    # ── Audit ─────────────────────────────────────────────────────────────
    audit_trail: list[dict]
