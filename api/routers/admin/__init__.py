"""
Admin router package — all endpoints require admin role.

Sub-modules:
  _agents.py  — agent definitions (CRUD) + user–agent bindings
  _users.py   — user management (create / update / list)
  _mcp.py     — MCP server registry (register / toggle / delete)

The combined `router` exposed here is mounted in api/main.py:
  app.include_router(admin_router)   → prefix /api/admin, tag "admin"

Callers outside this package only need:
  from api.routers.admin import router
"""

from fastapi import APIRouter

from api.routers.admin._agents import router as _agents_router
from api.routers.admin._users import router as _users_router
from api.routers.admin._mcp import router as _mcp_router

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(_agents_router)
router.include_router(_users_router)
router.include_router(_mcp_router)
