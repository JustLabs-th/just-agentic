#!/usr/bin/env python3
"""
just-agentic — Secure Multi-Agent CLI
Flow: rbac_guard → data_classifier → intent_guard → supervisor
       → human_approval → agents → supervisor → audit_log
"""

import os
import sys
from uuid import uuid4
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command

load_dotenv()

if not os.getenv("OPENAI_API_KEY") and os.getenv("LLM_PROVIDER", "openai") == "openai":
    print("ERROR: OPENAI_API_KEY not set. Copy .env.example → .env and add your key.")
    sys.exit(1)

from db import init_db
from graph.state import AgentState
from graph.secure_graph import build_secure_graph


def _ask_credentials() -> tuple[str, str, str, str]:
    """Returns (user_id, role, department, jwt_token).
    JWT mode: paste a Bearer token — role/dept extracted from token.
    Dev mode: enter user_id / role / department manually.
    """
    jwt_secret = os.getenv("JWT_SECRET", "")
    print("\nAuth mode: [1] JWT token  [2] Dev credentials (default)")
    mode = input("choice [1/2]: ").strip()

    if mode == "1" and jwt_secret:
        token = input("Bearer token: ").strip()
        return "", "", "", token   # rbac_guard will decode

    # Dev / plain credentials
    print("\nAvailable roles      : viewer | analyst | manager | admin")
    print("Available departments: engineering | devops | qa | data | security | all")
    user_id    = input("user_id   : ").strip() or "anonymous"
    role       = input("role      : ").strip() or "viewer"
    department = input("department: ").strip() or "all"
    return user_id, role, department, ""


def _print_new_ai_messages(messages: list, since: int) -> int:
    for msg in messages[since:]:
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            if content.strip():
                print(f"\n{content}")
    return len(messages)


def _handle_interrupt(payload: dict) -> bool:
    """Show interrupt info and ask user y/n. Returns True = approved."""
    agent  = payload.get("agent", "agent")
    intent = payload.get("intent", "")
    action = payload.get("action", "")

    print(f"\n{'─'*60}")
    print(f"  ⚠️  Approval Required")
    print(f"  Agent  : {agent}")
    print(f"  Intent : {intent}")
    print(f"  Action : {action}")
    print(f"{'─'*60}")

    while True:
        answer = input("  Approve? [y/N]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            print("  ✗ Cancelled.")
            return False


def _stream_task(app, state_or_cmd, config: dict, msg_count: int) -> tuple[list, int]:
    """Stream events and return (final_messages, msg_count)."""
    final_msgs = []
    current_node = None

    for event in app.stream(state_or_cmd, config, stream_mode="values"):
        s = event
        messages = s.get("messages", [])
        final_msgs = messages

        if s.get("status") == "permission_denied":
            err = s.get("error", "")
            if err != "user_rejected":          # user_rejected already printed
                print(f"\n  ⛔ PERMISSION DENIED: {err}")
            break

        active = s.get("current_agent", "")
        if active and active != current_node and active not in ("supervisor",):
            confidence = s.get("confidence")
            intent     = s.get("intent", "")
            label = f"→ {active.upper()}"
            if confidence is not None:
                label += f"  [{intent}  {confidence:.0%}]"
            print(f"\n[{label}]")
            current_node = active

        msg_count = _print_new_ai_messages(messages, msg_count)

    return final_msgs, msg_count


def run_task(task: str, app, history: list, user_id: str, role: str,
             department: str, thread_id: str, jwt_token: str = "") -> list:
    print(f"\n{'='*60}")
    print(f"[{role.upper()}] {task}")
    print(f"{'='*60}")

    config: dict = {"configurable": {"thread_id": thread_id}}

    state: AgentState = {
        "messages":      history + [HumanMessage(content=task)],
        "jwt_token":       jwt_token,
        "user_id":         user_id,
        "user_role":       role,
        "user_department": department,
        "clearance_level": 0,
        "allowed_tools": [],
        "context":       [],
        "visible_context": [],
        "stripped_levels": [],
        "data_classifications_accessed": [],
        "user_goal":     task,
        "current_agent": "supervisor",
        "plan":          [],
        "goal_for_agent": "",
        "working_memory": {},
        "tools_called":  [],
        "iteration":     0,
        "intent":        "",
        "confidence":    0.0,
        "routing_history": [],
        "retry_count":   {},
        "supervisor_log": [],
        "final_answer":  "",
        "status":        "planning",
        "error":         "",
        "audit_trail":   [],
    }

    msg_count  = len(history)
    final_msgs = state["messages"]

    # ── First run ──
    final_msgs, msg_count = _stream_task(app, state, config, msg_count)

    # ── Resume loop: handle interrupts until graph finishes ──
    while True:
        graph_state = app.get_state(config)
        if not graph_state.next:
            break   # graph finished (no pending nodes)

        # Extract interrupt payloads from pending tasks
        interrupts = []
        for task_info in (graph_state.tasks or []):
            for intr in (getattr(task_info, "interrupts", None) or []):
                interrupts.append(intr)

        if not interrupts:
            break   # interrupted for unknown reason — stop

        approved = _handle_interrupt(interrupts[0].value)
        final_msgs, msg_count = _stream_task(
            app, Command(resume=approved), config, msg_count
        )

    print(f"\n{'='*60}")
    return final_msgs


def main():
    init_db()

    print("just-agentic — Secure Multi-Agent Team")
    print("Agents: Supervisor | Backend | DevOps | QA")
    print("Type 'exit' to quit, 'whoami' to check role.\n")

    user_id, role, department, jwt_token = _ask_credentials()
    if jwt_token:
        print("\nLogged in via JWT token.\n")
    else:
        print(f"\nLogged in as '{user_id}' [{role} / {department}]\n")

    app      = build_secure_graph()
    history: list = []

    while True:
        try:
            task = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not task:
            continue
        if task.lower() == "exit":
            print("Goodbye.")
            break
        if task.lower() == "whoami":
            if jwt_token:
                print(f"  auth       : JWT token")
            else:
                print(f"  user_id    : {user_id}")
                print(f"  role       : {role}")
                print(f"  department : {department}")
            continue

        thread_id = str(uuid4())
        history = run_task(task, app, history, user_id, role, department, thread_id, jwt_token)


if __name__ == "__main__":
    main()
