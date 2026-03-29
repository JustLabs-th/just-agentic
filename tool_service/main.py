"""
Tool Execution Service — Option B isolation layer.

Runs as a separate container with:
  - internal-only Docker network (no outbound internet)
  - /app filesystem read-only
  - /tmp writable via tmpfs
  - CPU/RAM limits enforced by Docker + RLIMIT inside subprocess

Endpoints:
  POST /execute    — run a sandboxed tool
  GET  /healthz    — health check
"""

import os
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from tool_service.executor import run_command, run_python

app = FastAPI(title="just-agentic tool-service", docs_url=None, redoc_url=None)

_SECRET = os.getenv("TOOL_SERVICE_SECRET", "")

# ── Auth ──────────────────────────────────────────────────────────────────────

def _verify_auth(request: Request) -> None:
    if not _SECRET:
        return  # no secret configured → open (dev only)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != _SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Schema ────────────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    tool:      str
    inputs:    dict
    workspace: str | None = None
    timeout:   int = 60


class ExecuteResponse(BaseModel):
    output: str


# ── Endpoint ──────────────────────────────────────────────────────────────────

@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest, request: Request):
    _verify_auth(request)

    workspace = req.workspace or os.getenv("WORKSPACE_ROOT") or None

    match req.tool:
        case "run_shell":
            command = req.inputs.get("command", "")
            if not command:
                raise HTTPException(400, "inputs.command is required")
            output = run_command(command, workspace, req.timeout)

        case "run_tests":
            command = req.inputs.get("command", "pytest -q")
            output = run_command(command, workspace, req.timeout)

        case "execute_python":
            code = req.inputs.get("code", "")
            if not code:
                raise HTTPException(400, "inputs.code is required")
            output = run_python(code, min(req.timeout, 30))

        case _:
            raise HTTPException(400, f"Unknown tool: {req.tool!r}")

    return ExecuteResponse(output=output)


@app.get("/healthz")
def health():
    return {"status": "ok"}
