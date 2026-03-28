import re
from datetime import datetime
from pydantic import BaseModel, field_validator
from typing import Optional


class LoginRequest(BaseModel):
    mode: str  # "jwt" | "dev"
    token: Optional[str] = None        # JWT mode
    user_id: Optional[str] = None      # dev mode
    role: Optional[str] = None
    department: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    user_id: str
    role: str
    department: str
    clearance_level: int
    allowed_tools: list[str]


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None    # None = server generates new thread
    history: list[dict] = []           # [{role: "user"|"assistant", content: str}]


class ResumeRequest(BaseModel):
    approved: bool


# ── Admin: Agent definitions ───────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


class AgentDefinitionCreate(BaseModel):
    name: str
    display_name: str
    system_prompt: str
    allowed_tools: list[str]
    department: str

    @field_validator("name")
    @classmethod
    def name_must_be_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError("name must be lowercase alphanumeric/underscore/dash, starting with a letter")
        return v


class AgentDefinitionUpdate(BaseModel):
    display_name: Optional[str] = None
    system_prompt: Optional[str] = None
    allowed_tools: Optional[list[str]] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None


class AgentDefinitionResponse(BaseModel):
    id: int
    name: str
    display_name: str
    system_prompt: str
    allowed_tools: list[str]
    department: str
    is_active: bool
    is_default: bool
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Admin: User–agent bindings ────────────────────────────────────────────────

class UserAgentBindingCreate(BaseModel):
    user_id: str
    agent_name: str


class UserAgentBindingResponse(BaseModel):
    id: int
    user_id: str
    agent_name: str
    assigned_by: str
    assigned_at: datetime
    is_active: bool

    model_config = {"from_attributes": True}


# ── Knowledge base ─────────────────────────────────────────────────────────────

class KnowledgeUploadRequest(BaseModel):
    document_name: str
    content: str
    clearance_level: int = 1          # PUBLIC=1, INTERNAL=2, CONFIDENTIAL=3, SECRET=4
    department: Optional[str] = None  # None = accessible by all departments
    source_url: Optional[str] = None


class KnowledgeDocumentResponse(BaseModel):
    document_id: str
    document_name: str
    chunk_count: int
    clearance_level: int
    department: Optional[str]
    source_url: Optional[str]
    created_by: str
    created_at: datetime
