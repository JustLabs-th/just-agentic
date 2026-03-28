"""
Node: agent_resolver

Sits between department_guard and data_classifier.
Loads the user's allowed agent definitions from the DB and enforces
RBAC as a hard floor on each agent's tool list.

Populates: allowed_agents, agent_definitions, single_agent_mode
Falls back to is_default=True agents when user has no explicit bindings.
"""

from langchain_core.messages import AIMessage

from graph.state import AgentState


def agent_resolver_node(state: AgentState) -> AgentState:
    try:
        return _resolve(state)
    except Exception as exc:
        return {
            **state,
            "messages": [AIMessage(content=f"Agent resolver failed: {exc}")],
            "status": "permission_denied",
            "error": "agent_resolver_failed",
            "allowed_agents": [],
            "agent_definitions": [],
            "single_agent_mode": False,
        }


def _resolve(state: AgentState) -> AgentState:
    from db.models import AgentDefinition, UserAgentBinding
    from db.session import get_db

    user_id = state.get("user_id", "")
    rbac_tools = set(state.get("allowed_tools") or [])

    with get_db() as db:
        # Try user-specific bindings first
        bindings = (
            db.query(UserAgentBinding)
            .filter_by(user_id=user_id, is_active=True)
            .all()
        )
        agent_ids = [b.agent_definition_id for b in bindings]

        if agent_ids:
            definitions = (
                db.query(AgentDefinition)
                .filter(
                    AgentDefinition.id.in_(agent_ids),
                    AgentDefinition.is_active == True,  # noqa: E712
                )
                .all()
            )
        else:
            # No bindings → fall back to default agents
            definitions = (
                db.query(AgentDefinition)
                .filter_by(is_default=True, is_active=True)
                .all()
            )

        resolved = []
        for defn in definitions:
            # RBAC is the hard floor — intersect agent tools with what the user can access
            safe_tools = list(set(defn.allowed_tools) & rbac_tools)
            resolved.append({
                "name": defn.name,
                "display_name": defn.display_name,
                "system_prompt": defn.system_prompt,
                "allowed_tools": safe_tools,
                "department": defn.department,
            })

    allowed_agents = [d["name"] for d in resolved]

    return {
        **state,
        "allowed_agents": allowed_agents,
        "agent_definitions": resolved,
        "single_agent_mode": len(allowed_agents) == 1,
    }
