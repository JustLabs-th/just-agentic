"""
Supervisor Node

Responsibilities:
  - Ask the LLM which specialist agent should handle the current task
    (or FINISH if done)
  - Parse the LLM decision: agent name, intent, confidence score
  - Detect infinite loops (same agent chosen 3× in a row → force FINISH)
  - Bypass routing entirely when the user has exactly one allowed agent
  - Respect MAX_ITERATIONS hard cap

This is the ONLY LLM call in the security pipeline.
All upstream nodes (rbac_guard → prompt_injection_guard) are deterministic.

Routing decision format expected from LLM:
  {"agent": "<name>", "intent": "<category>", "confidence": 0.0–1.0}
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.graph import END

from config.prompts import SUPERVISOR_SYSTEM_PROMPT
from graph.state import AgentState
from llm.adapter import get_adapter

MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "8"))


def _load_project_context() -> str:
    """Load CONTEXT.md or README.md from WORKSPACE_ROOT if present."""
    workspace = os.getenv("WORKSPACE_ROOT", "")
    if not workspace:
        return ""
    for filename in ("CONTEXT.md", "README.md"):
        p = Path(workspace) / filename
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")[:3000]
                return f"--- Project context ({filename}) ---\n{content}\n---"
            except Exception:
                pass
    return ""
MAX_RETRIES_PER_AGENT = 2
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.55"))
LOOP_WINDOW = 3


def _valid_agents(state: AgentState) -> set[str]:
    """Return the set of agent names the user is allowed to use."""
    return set(state.get("allowed_agents") or [])


def supervisor_node(state: AgentState) -> AgentState:
    iteration = state.get("iteration", 0)
    routing_history: list[str] = list(state.get("routing_history") or [])
    retry_count: dict[str, int] = dict(state.get("retry_count") or {})
    supervisor_log: list[dict] = list(state.get("supervisor_log") or [])
    valid_agents = _valid_agents(state)

    # ── Hard stop: max iterations ──────────────────────────────────────────
    if iteration >= MAX_ITERATIONS:
        return _finish(state, "Reached maximum iterations.", iteration, routing_history,
                       retry_count, supervisor_log, error="max_iterations")

    # ── Loop detection: same agent repeated LOOP_WINDOW times ─────────────
    if (len(routing_history) >= LOOP_WINDOW
            and len(set(routing_history[-LOOP_WINDOW:])) == 1):
        stuck_agent = routing_history[-1]
        return _finish(
            state,
            f"Detected routing loop: '{stuck_agent}' called {LOOP_WINDOW} times with no progress.",
            iteration, routing_history, retry_count, supervisor_log,
            error="routing_loop",
        )

    # ── Single-agent mode: skip LLM on first turn ──────────────────────────
    if state.get("single_agent_mode") and not routing_history:
        agent_name = list(valid_agents)[0]
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "iteration": iteration + 1,
            "intent": "direct_route",
            "confidence": 1.0,
            "next_agent": agent_name,
            "reason": "single_agent_mode: bypassing LLM routing",
            "done": False,
        }
        supervisor_log.append(log_entry)
        return {
            **state,
            "current_agent": agent_name,
            "intent": "direct_route",
            "confidence": 1.0,
            "goal_for_agent": state.get("user_goal", ""),
            "iteration": iteration + 1,
            "routing_history": routing_history + [agent_name],
            "retry_count": retry_count,
            "supervisor_log": supervisor_log,
            "status": "working",
        }

    # ── Build context for supervisor LLM ──────────────────────────────────
    messages = state.get("messages", [])
    project_ctx = _load_project_context()
    context_parts = []
    if project_ctx:
        context_parts.append(project_ctx)
    context_parts += [
        f"Workspace: {os.getenv('WORKSPACE_ROOT', '(not set)')}",
        f"User goal: {state.get('user_goal', '')}",
        f"User role: {state.get('user_role', 'unknown')}",
        f"Allowed tools: {state.get('allowed_tools') or '(none)'}",
        f"Iteration: {iteration}/{MAX_ITERATIONS}",
    ]
    if state.get("plan"):
        context_parts.append(f"Plan: {state['plan']}")
    if state.get("working_memory"):
        context_parts.append(f"Working memory: {state['working_memory']}")
    if routing_history:
        context_parts.append(f"Routing history (last 5): {routing_history[-5:]}")

    # Inject dynamic agent descriptions
    agent_defs = state.get("agent_definitions") or []
    if agent_defs:
        agents_desc = "\n".join(
            f"- {d['name']}: {d.get('system_prompt', '')[:120].splitlines()[0]}"
            for d in agent_defs
        )
        context_parts.append(f"Available agents:\n{agents_desc}")

    for msg in messages[-6:]:
        role = getattr(msg, "type", "unknown")
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
        context_parts.append(f"[{role}]: {content[:500]}")

    raw = get_adapter().invoke(SUPERVISOR_SYSTEM_PROMPT, "\n".join(context_parts))
    decision = _parse_decision(raw, valid_agents)

    next_agent = decision["next_agent"]
    done = decision["done"]
    confidence = decision["confidence"]
    intent = decision["intent"]

    # ── Fallback: low confidence ───────────────────────────────────────────
    if not done and confidence < CONFIDENCE_THRESHOLD and next_agent in valid_agents:
        fallback = _fallback_agent(next_agent, valid_agents)
        if fallback != next_agent:
            decision["reason"] += f" [low confidence {confidence:.2f} → fallback to {fallback}]"
            next_agent = fallback
            decision["next_agent"] = fallback

    # ── Retry / escalation ────────────────────────────────────────────────
    if not done and next_agent in valid_agents:
        agent_retries = retry_count.get(next_agent, 0)
        last_result = _last_agent_result(messages)
        if last_result in ("empty", "error") and routing_history and routing_history[-1] == next_agent:
            if agent_retries >= MAX_RETRIES_PER_AGENT:
                return _finish(
                    state,
                    f"Agent '{next_agent}' failed after {MAX_RETRIES_PER_AGENT} retries. Escalating.",
                    iteration, routing_history, retry_count, supervisor_log,
                    error=f"escalation:{next_agent}",
                )
            retry_count[next_agent] = agent_retries + 1
            decision["goal_for_agent"] += f" [retry {retry_count[next_agent]}/{MAX_RETRIES_PER_AGENT}]"

    # ── Build log entry ───────────────────────────────────────────────────
    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "iteration": iteration + 1,
        "intent": intent,
        "confidence": confidence,
        "next_agent": next_agent,
        "reason": decision["reason"],
        "done": done,
    }
    supervisor_log.append(log_entry)
    routing_history.append(next_agent if not done else "finish")

    updates: dict = {
        **state,
        "current_agent": "supervisor",
        "iteration": iteration + 1,
        "intent": intent,
        "confidence": confidence,
        "goal_for_agent": decision.get("goal_for_agent", ""),
        "routing_history": routing_history,
        "retry_count": retry_count,
        "supervisor_log": supervisor_log,
        "status": "done" if done else "working",
    }

    if done:
        from langchain_core.messages import AIMessage as _AIMsg
        # Prefer final_response (user-facing) over goal_for_agent (agent instruction)
        final = (decision.get("final_response") or
                 decision.get("goal_for_agent") or
                 decision.get("reason") or
                 "Task complete.")
        updates["final_answer"] = final
        # Inject as AIMessage so the SSE stream picks it up as a visible message
        updates["messages"] = list(state.get("messages", [])) + [_AIMsg(content=final)]
        updates["current_agent"] = next_agent if next_agent in valid_agents else "supervisor"
    else:
        updates["current_agent"] = next_agent

    return updates


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fallback_agent(current: str, valid_agents: set[str]) -> str:
    """Pick a fallback agent that is not the current one."""
    # Prefer this priority order for the classic trio
    preferred = ["qa", "backend", "devops"]
    for candidate in preferred:
        if candidate in valid_agents and candidate != current:
            return candidate
    # Any other agent that isn't current
    for candidate in valid_agents:
        if candidate != current:
            return candidate
    return current


def _finish(state, message, iteration, routing_history, retry_count,
            supervisor_log, error="") -> AgentState:
    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "iteration": iteration + 1,
        "intent": state.get("intent", ""),
        "confidence": 0.0,
        "next_agent": "finish",
        "reason": message,
        "done": True,
        "error": error,
    }
    supervisor_log.append(log_entry)
    from langchain_core.messages import AIMessage as _AIMsg
    return {
        **state,
        "current_agent": "supervisor",
        "iteration": iteration + 1,
        "status": "done" if not error else "error",
        "error": error,
        "final_answer": message,
        "messages": list(state.get("messages", [])) + [_AIMsg(content=message)],
        "routing_history": routing_history + ["finish"],
        "retry_count": retry_count,
        "supervisor_log": supervisor_log,
    }


def _last_agent_result(messages: list) -> str:
    """Check if the last agent message was empty or an error."""
    from langchain_core.messages import AIMessage
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content or ""
            if not content.strip():
                return "empty"
            low = content.lower()
            if any(w in low for w in ("error", "traceback", "exception", "failed")):
                return "error"
            return "ok"
    return "ok"


def _parse_decision(content: str, valid_agents: set[str]) -> dict:
    """Parse supervisor JSON. Returns safe defaults on failure."""
    default = {
        "next_agent": "finish",
        "intent": "info_request",
        "confidence": 0.5,
        "reason": "",
        "goal_for_agent": "",
        "done": True,
    }
    try:
        clean = content.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())

        next_agent = str(data.get("next_agent", "finish")).lower()
        done = bool(data.get("done", False))
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        if next_agent not in valid_agents:
            done = True

        return {
            "next_agent": next_agent,
            "intent": str(data.get("intent", "info_request")),
            "confidence": confidence,
            "reason": str(data.get("reason", "")),
            "goal_for_agent": str(data.get("goal_for_agent", "")),
            "final_response": str(data.get("final_response", "")),
            "done": done,
        }
    except (json.JSONDecodeError, AttributeError, ValueError):
        pass

    # Fallback: keyword scan against dynamic valid_agents
    lower = content.lower()
    for agent in valid_agents:
        if agent in lower:
            return {**default, "next_agent": agent, "done": False, "confidence": 0.4}

    return default
