"""
Shared AgentState factory — used by both API and worker.
Avoids duplicating message-building logic across processes.
"""

from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState


def build_initial_state(
    message: str,
    history: list[dict],
    user_ctx: dict,
    image: str | None = None,
) -> AgentState:
    """
    Build AgentState from primitive request data.

    Args:
        message:   The user's current message.
        history:   List of {"role": "user"|"assistant", "content": str} dicts.
        user_ctx:  {"user_id": str, "role": str, "department": str}
        image:     Optional base64 or URL image string for multimodal input.
    """
    msgs: list = []
    for m in history:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))

    if image:
        last_human = HumanMessage(content=[
            {"type": "text",      "text": message},
            {"type": "image_url", "image_url": {"url": image}},
        ])
    else:
        last_human = HumanMessage(content=message)

    return {
        "messages":      msgs + [last_human],
        "jwt_token":       "",
        "user_id":         user_ctx["user_id"],
        "user_role":       user_ctx["role"],
        "user_department": user_ctx["department"],
        "clearance_level": 0,
        "allowed_tools":   [],
        "context":         [],
        "visible_context": [],
        "stripped_levels": [],
        "data_classifications_accessed": [],
        "user_goal":       message,
        "current_agent":   "supervisor",
        "plan":            [],
        "goal_for_agent":  "",
        "working_memory":  {},
        "tools_called":    [],
        "iteration":       0,
        "intent":          "",
        "confidence":      0.0,
        "routing_history": [],
        "retry_count":     {},
        "supervisor_log":  [],
        "final_answer":    "",
        "status":          "planning",
        "error":           "",
        "audit_trail":     [],
    }
