"""
Dynamic agent factory.

Creates a LangGraph node function at runtime from an AgentDefinition dict
stored in state["agent_definitions"]. Tool list is already RBAC-intersected
by agent_resolver — no need to re-intersect here.
"""

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from graph.agents._utils import extract_tools_called, build_prompt_with_tools
from graph.state import AgentState
from llm.adapter import get_adapter
from tools import ALL_TOOLS, set_role_context
from tools._safety import set_tool_context


def dynamic_agent_node(agent_name: str):
    """Return a LangGraph-compatible node function for the given agent name."""

    def _node(state: AgentState) -> AgentState:
        # Look up definition from state (already RBAC-intersected by agent_resolver)
        defs = {d["name"]: d for d in (state.get("agent_definitions") or [])}
        defn = defs.get(agent_name)

        if defn is None:
            msg = AIMessage(content=f"Agent '{agent_name}' not found in resolved definitions.")
            return {**state, "messages": [msg], "current_agent": agent_name, "status": "error"}

        allowed = set(defn.get("allowed_tools") or [])
        tools = [t for t in ALL_TOOLS if t.name in allowed]

        if not tools:
            msg = AIMessage(
                content=f"Permission denied: '{agent_name}' has no accessible tools for your role."
            )
            return {**state, "messages": [msg], "current_agent": agent_name, "status": "done"}

        set_role_context(
            state.get("user_role", ""),
            state.get("user_department", "all"),
            state.get("clearance_level", 0),
        )
        set_tool_context(state.get("user_id", ""))

        agent = create_react_agent(
            get_adapter().chat_model(),
            tools=tools,
            prompt=build_prompt_with_tools(defn["system_prompt"], list(allowed)),
        )

        messages = list(state.get("messages", []))
        goal = state.get("goal_for_agent", "")
        if goal:
            messages = messages + [HumanMessage(content=f"[Supervisor]: {goal}")]

        result = agent.invoke({"messages": messages})
        new_calls = extract_tools_called(result["messages"])
        return {
            **state,
            "messages": result["messages"],
            "current_agent": agent_name,
            "tools_called": list(state.get("tools_called") or []) + new_calls,
        }

    _node.__name__ = f"{agent_name}_node"
    return _node
