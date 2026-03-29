#!/usr/bin/env python3
"""
just-agentic CLI — thin client mode

All LLM, RBAC, and agent logic runs on the server.
This client handles:
  - Login (JWT or dev mode)
  - SSE streaming from /api/agent/chat
  - Human approval via /api/agent/resume
  - Local file operations (workspace context shown to user)
"""

import json
import os
import sys
import threading
import itertools
import time
from uuid import uuid4

import requests

SERVER = os.getenv("JA_SERVER", "http://localhost:8000").rstrip("/")
WORKSPACE = os.getcwd()


# ── Spinner ────────────────────────────────────────────────────────────────────

class _Spinner:
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label="Thinking"):
        self._label = label
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        for f in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            print(f"\r  {f} {self._label}...", end="", flush=True)
            time.sleep(0.08)
        print(f"\r{' ' * (len(self._label) + 16)}\r", end="", flush=True)

    def start(self):  self._t.start(); return self
    def stop(self):   self._stop.set(); self._t.join()
    def update(self, label): self._label = label


# ── SSE reader ─────────────────────────────────────────────────────────────────

def _stream_sse(response) -> dict:
    """Yield parsed SSE event dicts from a streaming response."""
    buf = ""
    for chunk in response.iter_content(chunk_size=None):
        buf += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            for line in block.splitlines():
                if line.startswith("data: "):
                    try:
                        yield json.loads(line[6:])
                    except json.JSONDecodeError:
                        pass


# ── Auth ───────────────────────────────────────────────────────────────────────

def login() -> tuple[str, str, str, str, str]:
    """Returns (token, user_id, role, department, clearance_level)."""
    jwt_env = os.getenv("JA_TOKEN", "")

    print(f"\nServer   : {SERVER}")
    print(f"Workspace: {WORKSPACE}\n")

    if jwt_env:
        mode = "1"
    else:
        print("Auth: [1] JWT token  [2] Dev credentials (default)")
        mode = input("choice [1/2]: ").strip() or "2"

    if mode == "1":
        token = jwt_env or input("Bearer token: ").strip()
        payload = {"mode": "jwt", "token": token}
    else:
        print("\nRoles      : viewer | analyst | manager | admin")
        print("Departments: engineering | devops | qa | data | security | all")
        user_id    = input("user_id   : ").strip() or "anonymous"
        role       = input("role      : ").strip() or "viewer"
        department = input("department: ").strip() or "all"
        payload = {"mode": "dev", "user_id": user_id, "role": role, "department": department}

    try:
        r = requests.post(f"{SERVER}/api/auth/login", json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        return (
            data["access_token"],
            data["user_id"],
            data["role"],
            data["department"],
            str(data["clearance_level"]),
        )
    except requests.ConnectionError:
        print(f"\n  ✗ Cannot connect to server: {SERVER}")
        print("  Set JA_SERVER=https://your-company-server.com")
        sys.exit(1)
    except requests.HTTPError as e:
        detail = e.response.json().get("detail", str(e)) if e.response else str(e)
        print(f"\n  ✗ Login failed: {detail}")
        sys.exit(1)


# ── Stream a chat turn ─────────────────────────────────────────────────────────

def _do_stream(endpoint: str, payload: dict, headers: dict) -> tuple[str | None, dict | None]:
    """
    Stream SSE from endpoint. Returns (thread_id, interrupt_payload).
    interrupt_payload is set when approval_required is received.
    """
    spinner = _Spinner().start()
    spinner_active = True
    streaming = False
    thread_id = None
    interrupt = None
    current_agent = None

    def stop_spinner():
        nonlocal spinner_active
        if spinner_active:
            spinner.stop()
            spinner_active = False

    try:
        with requests.post(
            f"{SERVER}{endpoint}",
            json=payload,
            headers=headers,
            stream=True,
            timeout=300,
        ) as resp:
            resp.raise_for_status()

            for event in _stream_sse(resp):
                etype = event.get("type")

                if etype == "thread_id":
                    thread_id = event.get("thread_id")

                elif etype == "agent_switch":
                    agent = event.get("agent", "")
                    intent = event.get("intent", "")
                    conf = event.get("confidence", 0)
                    current_agent = agent
                    stop_spinner()
                    if streaming:
                        print()
                        streaming = False
                    label = f"→ {agent.upper()}"
                    if intent:
                        label += f"  [{intent}  {conf:.0%}]"
                    print(f"\n[{label}]")
                    spinner_active = True
                    spinner = _Spinner(f"{agent.capitalize()} thinking").start()

                elif etype == "tool_call":
                    tool = event.get("tool", "")
                    inp = event.get("input", {})
                    stop_spinner()
                    # Show primary arg inline
                    arg = next(
                        (str(v) for k, v in inp.items()
                         if k in ("path", "command", "query", "keyword", "url")),
                        ""
                    )
                    hint = f" {arg[:60]}" if arg else ""
                    print(f"  ▸ {tool}{hint}")

                elif etype == "message":
                    content = event.get("content", "")
                    if content:
                        stop_spinner()
                        if not streaming:
                            print()
                            streaming = True
                        print(content, end="", flush=True)

                elif etype == "approval_required":
                    stop_spinner()
                    if streaming:
                        print()
                        streaming = False
                    interrupt = event
                    break

                elif etype == "permission_denied":
                    stop_spinner()
                    print(f"\n  ⛔ Permission denied: {event.get('error', '')}")
                    break

                elif etype in ("done", "error"):
                    stop_spinner()
                    if streaming:
                        print()
                    if etype == "error":
                        print(f"\n  ✗ Error: {event.get('error', '')}")
                    break

    except requests.ConnectionError:
        stop_spinner()
        print(f"\n  ✗ Lost connection to server")
    except requests.HTTPError as e:
        stop_spinner()
        detail = e.response.json().get("detail", str(e)) if e.response else str(e)
        print(f"\n  ✗ {detail}")
    finally:
        if spinner_active:
            spinner.stop()

    return thread_id, interrupt


# ── Main loop ──────────────────────────────────────────────────────────────────

def run_task(task: str, token: str, history: list, thread_id: str | None) -> tuple[list, str | None]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "message": task,
        "history": [{"role": m["role"], "content": m["content"]} for m in history],
        "thread_id": thread_id,
    }

    new_thread_id, interrupt = _do_stream("/api/agent/chat", payload, headers)
    thread_id = new_thread_id or thread_id

    # Handle interrupt loop
    while interrupt:
        agent  = interrupt.get("agent", "agent")
        intent = interrupt.get("intent", "")
        action = interrupt.get("action", "")

        print(f"\n{'─'*60}")
        print(f"  ⚠️  Approval Required")
        print(f"  Agent  : {agent}")
        print(f"  Intent : {intent}")
        print(f"  Action : {action}")
        print(f"{'─'*60}")

        answer = input("  Approve? [y/N]: ").strip().lower()
        approved = answer in ("y", "yes")
        if not approved:
            print("  ✗ Cancelled.")

        _, interrupt = _do_stream(
            f"/api/agent/resume/{thread_id}",
            {"approved": approved},
            headers,
        )

    history = history + [{"role": "user", "content": task}]
    return history, thread_id


def main():
    token, user_id, role, department, clearance = login()
    print(f"\nLogged in as '{user_id}' [{role} / {department} / L{clearance}]")
    print("Type 'exit' to quit, 'whoami' to check identity.\n")

    history: list = []
    thread_id: str | None = None

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
            print(f"  server    : {SERVER}")
            print(f"  workspace : {WORKSPACE}")
            print(f"  user_id   : {user_id}")
            print(f"  role      : {role}")
            print(f"  department: {department}")
            print(f"  clearance : L{clearance}")
            continue

        print(f"\n{'='*60}")
        history, thread_id = run_task(task, token, history, thread_id)
        print(f"\n{'='*60}")


if __name__ == "__main__":
    main()
