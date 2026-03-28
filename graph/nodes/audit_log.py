"""
Node 5: Audit Log
- Runs after every completed turn (before returning to caller)
- Writes an immutable AuditRecord
- Never raises — audit failure must not block the response
"""

from langchain_core.messages import AIMessage

from graph.state import AgentState
from security.audit import logger as audit_logger


def _extract_final_response(state: AgentState) -> str:
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            if content.strip():
                return content
    return ""


def audit_log_node(state: AgentState) -> AgentState:
    final_response = _extract_final_response(state)

    try:
        record = audit_logger.log(
            user_id=state.get("user_id", "unknown"),
            role=state.get("user_role", "unknown"),
            department=state.get("user_department", "unknown"),
            clearance_level=state.get("clearance_level", 0),
            query=state.get("messages", [{}])[0].content if state.get("messages") else "",
            response=final_response,
            tools_used=state.get("tools_called", []),
            data_classifications_accessed=state.get("data_classifications_accessed", []),
            stripped_classifications=state.get("stripped_levels", []),
            iteration_count=state.get("iteration", 0),
            status=state.get("status", "ok"),
            error=state.get("error", ""),
        )
        audit_trail = list(state.get("audit_trail", []))
        audit_trail.append({
            "timestamp": record.timestamp,
            "response_hash": record.response_hash,
            "tools_used": record.tools_used,
        })
    except Exception as exc:
        audit_trail = list(state.get("audit_trail", []))
        audit_trail.append({"error": f"audit failed: {exc}"})

    return {
        **state,
        "final_answer": final_response,
        "audit_trail": audit_trail,
    }
