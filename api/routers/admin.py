"""
Admin router — super-admin CRUD for agent definitions and user–agent bindings.
All endpoints require admin role.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_admin
from api.schemas import (
    AgentDefinitionCreate, AgentDefinitionUpdate, AgentDefinitionResponse,
    UserAgentBindingCreate, UserAgentBindingResponse,
    MCPServerCreate, MCPServerResponse,
)
from db.models import AgentDefinition, UserAgentBinding, MCPServer
from db.session import get_db
from graph.secure_graph import invalidate_graph_cache
from security.jwt_auth import UserContext

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Agent definitions ─────────────────────────────────────────────────────────

@router.post("/agents", response_model=AgentDefinitionResponse, status_code=201)
def create_agent(
    body: AgentDefinitionCreate,
    admin: UserContext = Depends(require_admin),
):
    with get_db() as db:
        if db.query(AgentDefinition).filter_by(name=body.name).first():
            raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists")

        agent = AgentDefinition(
            name=body.name,
            display_name=body.display_name,
            system_prompt=body.system_prompt,
            allowed_tools=body.allowed_tools,
            department=body.department,
            is_default=False,
            is_active=True,
            created_by=admin.user_id,
        )
        db.add(agent)
        db.flush()
        db.refresh(agent)
        result = _to_response(agent)

    invalidate_graph_cache()
    return result


@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents(admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        agents = db.query(AgentDefinition).order_by(AgentDefinition.name).all()
        return [_to_response(a) for a in agents]


@router.get("/agents/{agent_name}", response_model=AgentDefinitionResponse)
def get_agent(agent_name: str, admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        agent = db.query(AgentDefinition).filter_by(name=agent_name).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        return _to_response(agent)


@router.patch("/agents/{agent_name}", response_model=AgentDefinitionResponse)
def update_agent(
    agent_name: str,
    body: AgentDefinitionUpdate,
    admin: UserContext = Depends(require_admin),
):
    with get_db() as db:
        agent = db.query(AgentDefinition).filter_by(name=agent_name).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

        for field, value in body.model_dump(exclude_none=True).items():
            setattr(agent, field, value)
        db.flush()
        db.refresh(agent)
        result = _to_response(agent)

    invalidate_graph_cache()
    return result


@router.delete("/agents/{agent_name}", status_code=204)
def delete_agent(agent_name: str, admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        agent = db.query(AgentDefinition).filter_by(name=agent_name).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        agent.is_active = False

    invalidate_graph_cache()


# ── User–agent bindings ───────────────────────────────────────────────────────

@router.post("/agents/{agent_name}/bindings", response_model=UserAgentBindingResponse, status_code=201)
def bind_user(
    agent_name: str,
    body: UserAgentBindingCreate,
    admin: UserContext = Depends(require_admin),
):
    with get_db() as db:
        agent = db.query(AgentDefinition).filter_by(name=agent_name, is_active=True).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

        existing = (
            db.query(UserAgentBinding)
            .filter_by(user_id=body.user_id, agent_definition_id=agent.id)
            .first()
        )
        if existing:
            if existing.is_active:
                raise HTTPException(status_code=409, detail="Binding already exists")
            # Re-activate soft-deleted binding
            existing.is_active = True
            existing.assigned_by = admin.user_id
            db.flush()
            db.refresh(existing)
            return _binding_to_response(existing, agent_name)

        binding = UserAgentBinding(
            user_id=body.user_id,
            agent_definition_id=agent.id,
            assigned_by=admin.user_id,
            is_active=True,
        )
        db.add(binding)
        db.flush()
        db.refresh(binding)
        return _binding_to_response(binding, agent_name)


@router.get("/users/{user_id}/agents", response_model=list[UserAgentBindingResponse])
def list_user_agents(user_id: str, admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        bindings = (
            db.query(UserAgentBinding)
            .filter_by(user_id=user_id, is_active=True)
            .all()
        )
        results = []
        for b in bindings:
            agent = db.query(AgentDefinition).filter_by(id=b.agent_definition_id).first()
            results.append(_binding_to_response(b, agent.name if agent else "unknown"))
        return results


@router.delete("/bindings/{binding_id}", status_code=204)
def revoke_binding(binding_id: int, admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        binding = db.query(UserAgentBinding).filter_by(id=binding_id).first()
        if not binding:
            raise HTTPException(status_code=404, detail="Binding not found")
        binding.is_active = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(agent: AgentDefinition) -> AgentDefinitionResponse:
    return AgentDefinitionResponse(
        id=agent.id,
        name=agent.name,
        display_name=agent.display_name,
        system_prompt=agent.system_prompt,
        allowed_tools=agent.allowed_tools or [],
        department=agent.department,
        is_active=agent.is_active,
        is_default=agent.is_default,
        created_by=agent.created_by,
        created_at=agent.created_at,
    )


# ── MCP Servers ───────────────────────────────────────────────────────────────

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


def _binding_to_response(binding: UserAgentBinding, agent_name: str) -> UserAgentBindingResponse:
    return UserAgentBindingResponse(
        id=binding.id,
        user_id=binding.user_id,
        agent_name=agent_name,
        assigned_by=binding.assigned_by,
        assigned_at=binding.assigned_at,
        is_active=binding.is_active,
    )
