"""
MCP (Model Context Protocol) server registry.

Endpoints (prefix /api/admin):
  POST   /mcp          — register external MCP server
  GET    /mcp          — list all servers
  PATCH  /mcp/{name}   — toggle active state
  DELETE /mcp/{name}   — remove server

Changes here invalidate the graph cache so the next request reloads MCP tools.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_admin
from api.schemas import MCPServerCreate, MCPServerResponse
from db.models import MCPServer
from db.session import get_db
from graph.secure_graph import invalidate_graph_cache
from security.jwt_auth import UserContext

router = APIRouter()


@router.post("/mcp", response_model=MCPServerResponse, status_code=201)
def register_mcp_server(body: MCPServerCreate, admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        if db.query(MCPServer).filter_by(name=body.name).first():
            raise HTTPException(status_code=409, detail=f"MCP server '{body.name}' already exists")
        server = MCPServer(
            name=body.name,
            url=body.url,
            transport=body.transport,
            description=body.description,
            created_by=admin.user_id,
        )
        db.add(server)
        db.flush()
        resp = MCPServerResponse.model_validate(server)
    invalidate_graph_cache()
    return resp


@router.get("/mcp", response_model=list[MCPServerResponse])
def list_mcp_servers(admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        return [MCPServerResponse.model_validate(s) for s in db.query(MCPServer).all()]


@router.patch("/mcp/{name}")
def update_mcp_server(
    name: str,
    is_active: bool,
    admin: UserContext = Depends(require_admin),
):
    with get_db() as db:
        server = db.query(MCPServer).filter_by(name=name).first()
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
        server.is_active = is_active
    invalidate_graph_cache()
    return {"status": "updated"}


@router.delete("/mcp/{name}", status_code=204)
def delete_mcp_server(name: str, admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        server = db.query(MCPServer).filter_by(name=name).first()
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
        db.delete(server)
    invalidate_graph_cache()
