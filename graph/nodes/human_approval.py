"""
Human Approval Node

Sits between supervisor and agent nodes.
For dangerous actions (write / execute / destructive), pauses the graph
via interrupt() and waits for explicit user approval before proceeding.

Safe actions pass through without prompting.
"""

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from graph.state import AgentState

# Intents that always require approval
_APPROVAL_INTENTS = {"infrastructure_write", "code_write"}

# Keywords in goal_for_agent that flag a dangerous action
_DANGEROUS_KEYWORDS = [
    "delete", "remove", "rm ", "drop", "truncate", "overwrite",
    "format", "wipe", "destroy", "kill", "terminate",
    "ลบ", "ลบไฟล์", "ลบ folder",
]


def _is_dangerous(state: AgentState) -> bool:
    intent = state.get("intent", "")
    goal = (state.get("goal_for_agent") or "").lower()

    # LLM-assigned intent check
    if intent in _APPROVAL_INTENTS:
        return True
    if any(kw in goal for kw in _DANGEROUS_KEYWORDS):
        return True

    # Independent check: scan the original user goal directly (not LLM-assigned).
    # This fires even if the LLM misclassifies the intent.
    user_goal = (state.get("user_goal") or "").lower()
    if any(kw in user_goal for kw in _DANGEROUS_KEYWORDS):
        return True

    return False


def human_approval_node(state: AgentState) -> AgentState:
    """Interrupt for user approval if action is potentially destructive."""
    if not _is_dangerous(state):
        return state  # safe — pass through silently

    agent = state.get("current_agent", "agent")
    goal = state.get("goal_for_agent", "(no description)")
    intent = state.get("intent", "unknown")

    # Pause graph — main.py will catch this and prompt the user
    approved: bool = interrupt({
        "agent":  agent,
        "intent": intent,
        "action": goal,
    })

    if not approved:
        cancel_msg = AIMessage(
            content=f"Action cancelled by user.\nAgent: {agent}\nIntent: {intent}\nAction: {goal}"
        )
        return {
            **state,
            "messages":   [cancel_msg],
            "status":     "permission_denied",
            "error":      "user_rejected",
            "final_answer": "Action was cancelled.",
        }

    # Approved — continue to agent unchanged
    return state
