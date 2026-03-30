#!/usr/bin/env python3
"""
just-agentic CLI — thin client mode

All LLM, RBAC, and agent logic runs on the server.
This client handles:
  - Login (JWT, credentials, or dev mode)
  - SSE streaming from /api/agent/chat
  - Human approval via /api/agent/resume
  - Local tool execution (local_exec mode) — runs tools in /workspace
    so the client's host environment (Node.js, git, etc.) is available
"""

import glob as _glob
import json
import os
import subprocess
import sys
import tempfile
import threading
import itertools
import time
from uuid import uuid4

import requests

SERVER = os.getenv("JA_SERVER", "http://localhost:8000").rstrip("/")
WORKSPACE = os.getcwd()   # /workspace inside the container


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

def _stream_sse(response):
    """Yield parsed SSE event dicts from a streaming response."""
    buf = ""
    for chunk in response.iter_content(chunk_size=None):
        decoded = chunk.decode("utf-8", errors="replace")
        buf += decoded.encode("utf-8", errors="replace").decode("utf-8")
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            for line in block.splitlines():
                if line.startswith("data: "):
                    try:
                        safe = line[6:].encode("utf-8", errors="replace").decode("utf-8")
                        yield json.loads(safe)
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
        print("Auth: [1] JWT token  [2] Password  [3] Dev credentials")
        mode = input("choice [1/2/3]: ").strip() or "2"

    if mode == "1":
        token = jwt_env or input("Bearer token: ").strip()
        payload = {"mode": "jwt", "token": token}

    elif mode == "2":
        user_id  = input("Username: ").strip()
        password = input("Password: ").strip()
        payload  = {"mode": "credentials", "user_id": user_id, "password": password}

    else:
        print("\nRoles      : viewer | analyst | manager | admin")
        print("Departments: engineering | devops | qa | data | security | all")
        user_id    = input("user_id   : ").strip() or "anonymous"
        role       = input("role      : ").strip() or "viewer"
        department = input("department: ").strip() or "all"
        payload    = {"mode": "dev", "user_id": user_id, "role": role, "department": department}

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


# ── Local tool execution ───────────────────────────────────────────────────────

def _safe_path(path: str) -> str:
    """Resolve path relative to WORKSPACE, block traversal outside it."""
    if os.path.isabs(path):
        norm = os.path.normpath(path)
        if norm.startswith("/workspace"):
            return norm
        return os.path.normpath(os.path.join(WORKSPACE, path.lstrip("/")))
    return os.path.normpath(os.path.join(WORKSPACE, path))


def _execute_local(tool: str, inputs: dict) -> str:
    """Run a tool locally inside /workspace where the host env is available."""
    try:
        if tool in ("run_shell", "run_tests"):
            cmd = inputs.get("command", "")
            if not cmd:
                return "(no command provided)"
            result = subprocess.run(
                cmd, shell=True, cwd=WORKSPACE,
                capture_output=True, text=True, timeout=180,
            )
            out = result.stdout or ""
            err = result.stderr or ""
            return (out + (f"\n[stderr]\n{err}" if err else "")).strip() or "(no output)"

        elif tool == "execute_python":
            code = inputs.get("code", "")
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, dir="/tmp") as f:
                f.write(code)
                fname = f.name
            try:
                result = subprocess.run(
                    ["python3", fname], cwd=WORKSPACE,
                    capture_output=True, text=True, timeout=60,
                )
                return (result.stdout + result.stderr).strip() or "(no output)"
            finally:
                try:
                    os.unlink(fname)
                except OSError:
                    pass

        elif tool == "read_file":
            path = _safe_path(inputs.get("path", ""))
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()

        elif tool == "write_file":
            path = _safe_path(inputs.get("path", ""))
            content = inputs.get("content", "")
            os.makedirs(os.path.dirname(path) or WORKSPACE, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Written: {inputs.get('path', '')}"

        elif tool == "edit_file":
            path = _safe_path(inputs.get("path", ""))
            old_str = inputs.get("old_string", "")
            new_str = inputs.get("new_string", "")
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            if old_str not in content:
                return f"Error: old_string not found in {inputs.get('path', '')}"
            with open(path, "w", encoding="utf-8") as f:
                f.write(content.replace(old_str, new_str, 1))
            return f"Edited: {inputs.get('path', '')}"

        elif tool == "list_files":
            path = _safe_path(inputs.get("path", "."))
            if os.path.isdir(path):
                entries = sorted(os.listdir(path))
            else:
                entries = [os.path.basename(p) for p in _glob.glob(path)]
            return "\n".join(entries) if entries else "(empty)"

        elif tool == "search_code":
            keyword = inputs.get("keyword", "")
            result = subprocess.run(
                ["grep", "-rn", keyword, "."],
                cwd=WORKSPACE, capture_output=True, text=True, timeout=30,
            )
            return result.stdout.strip() or "(no matches)"

        elif tool == "git_status":
            result = subprocess.run(
                ["git", "status"], cwd=WORKSPACE,
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip()

        elif tool == "read_log":
            path = _safe_path(inputs.get("path", ""))
            lines = int(inputs.get("lines", 100))
            with open(path, encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-lines:]).strip()

        elif tool == "get_env":
            key = inputs.get("key", "")
            return os.getenv(key, f"(env var '{key}' not set)")

        else:
            return f"[tool '{tool}' not available in local mode]"

    except subprocess.TimeoutExpired:
        return "Error: command timed out"
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


# ── Stream a chat turn ─────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    """Remove surrogate characters that break JSON serialization."""
    return s.encode("utf-8", errors="replace").decode("utf-8")


def _do_stream(
    endpoint: str,
    payload: dict,
    headers: dict,
    on_tool_request=None,
) -> tuple[str | None, dict | None]:
    """
    Stream SSE from endpoint.

    on_tool_request: optional callable(call_id, tool, inputs, thread_id) invoked
    when a tool_call_request event arrives (local_exec mode).

    Returns (thread_id, interrupt_payload).
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
            timeout=600,   # long timeout — local tool execution can take a while
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
                    arg = next(
                        (str(v) for k, v in inp.items()
                         if k in ("path", "command", "query", "keyword", "url")),
                        "",
                    )
                    hint = f" {arg[:60]}" if arg else ""
                    print(f"  ▸ {tool}{hint}")

                elif etype == "tool_call_request" and on_tool_request:
                    # local_exec: worker delegated this tool to us
                    call_id = event.get("call_id", "")
                    tool    = event.get("tool", "")
                    inputs  = event.get("input", {})
                    stop_spinner()
                    if streaming:
                        print()
                        streaming = False
                    arg = next(
                        (str(v) for k, v in inputs.items()
                         if k in ("path", "command", "query", "keyword", "url")),
                        "",
                    )
                    hint = f" {arg[:60]}" if arg else ""
                    print(f"  ▸ {tool}{hint}  [local]")
                    spinner_active = True
                    spinner = _Spinner(f"Running {tool}").start()
                    on_tool_request(call_id, tool, inputs, thread_id or "")
                    stop_spinner()

                elif etype == "message":
                    content = event.get("content", "")
                    if content:
                        content = content.encode("utf-8", errors="replace").decode("utf-8")
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
        print("\n  ✗ Lost connection to server")
    except requests.HTTPError as e:
        stop_spinner()
        detail = e.response.json().get("detail", str(e)) if e.response else str(e)
        print(f"\n  ✗ {detail}")
    finally:
        if spinner_active:
            spinner.stop()

    return thread_id, interrupt


# ── Main loop ──────────────────────────────────────────────────────────────────

def run_task(
    task: str,
    token: str,
    history: list,
    thread_id: str | None,
) -> tuple[list, str | None]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Always use a fresh thread_id per turn — prevents replaying old checkpoints.
    turn_thread_id = str(uuid4())

    payload = {
        "message":    _clean(task),
        "history":    [{"role": m["role"], "content": _clean(m["content"])} for m in history],
        "thread_id":  turn_thread_id,
        "local_exec": True,   # tools run locally in /workspace
    }

    def _handle_tool(call_id: str, tool: str, inputs: dict, tid: str) -> None:
        output = _execute_local(tool, inputs)
        try:
            requests.post(
                f"{SERVER}/api/agent/tool-result/{tid}",
                json={"call_id": call_id, "output": output},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
        except Exception as e:
            print(f"  ✗ Failed to send tool result: {e}")

    new_thread_id, interrupt = _do_stream(
        "/api/agent/chat", payload, headers, on_tool_request=_handle_tool
    )
    thread_id = new_thread_id or turn_thread_id

    # Handle interrupt loop (human approval)
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

        try:
            answer = input("  Approve? [y/N]: ")
        except EOFError:
            answer = ""
        answer = answer.strip().lower().replace("\r", "")
        approved = answer.startswith("y")
        if not approved:
            print("  ✗ Cancelled.")

        _, interrupt = _do_stream(
            f"/api/agent/resume/{thread_id}",
            {"approved": approved},
            headers,
            on_tool_request=_handle_tool,
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
