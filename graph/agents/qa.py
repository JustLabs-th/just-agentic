from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from config.prompts import QA_SYSTEM_PROMPT
from llm.adapter import get_adapter
from graph.agents._utils import extract_tools_called, build_prompt_with_tools
from graph.state import AgentState
from tools import ALL_TOOLS, set_role_context
from tools._safety import set_tool_context


def qa_node(state: AgentState) -> AgentState:
    """QA agent: tests, logs, checklists — tools filtered by RBAC."""
    allowed = set(state.get("allowed_tools") or [])
    tools = [t for t in ALL_TOOLS if t.name in allowed]

    if not tools:
        msg = AIMessage(content="Permission denied: your role does not have access to any QA tools.")
        return {**state, "messages": [msg], "current_agent": "qa", "status": "done"}

    set_role_context(
        state.get("user_role", ""),
        state.get("user_department", "all"),
        state.get("clearance_level", 0),
    )
    set_tool_context(state.get("user_id", ""))

    agent = create_react_agent(
        get_adapter().chat_model(),
        tools=tools,
        prompt=build_prompt_with_tools(QA_SYSTEM_PROMPT, list(allowed)),
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
        "current_agent": "qa",
        "tools_called": list(state.get("tools_called") or []) + new_calls,
    }
