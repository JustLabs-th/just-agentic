from pydantic import BaseModel
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
