"""
JWT Auth — decode a Bearer token and return UserContext.
Requires: pip install PyJWT
Secret:   JWT_SECRET env var
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from security.rbac import get_policy, get_department_policy


@dataclass
class UserContext:
    user_id:    str
    role:       str
    department: str
    clearance_level: int


def decode_token(token: str) -> UserContext:
    """
    Decode and validate a JWT Bearer token.
    Expected payload: {"sub": "<user_id>", "role": "<role>", "dept": "<dept>"}
    Raises ValueError on invalid / expired tokens.
    Raises RuntimeError if JWT_SECRET is not set.
    """
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET env var is not set")

    try:
        import jwt
        payload = jwt.decode(
            token, secret,
            algorithms=["HS256"],
            options={"require": ["sub", "role", "dept", "exp"]},
        )
    except Exception as exc:
        raise ValueError(f"Invalid or expired token: {exc}") from exc

    user_id    = payload.get("sub", "")
    role       = payload.get("role", "viewer")
    department = payload["dept"]

    if not user_id:
        raise ValueError("Token missing 'sub' claim")

    get_policy(role)                    # raises PermissionError on unknown role
    get_department_policy(department)   # raises PermissionError on unknown dept

    from security.rbac import effective_clearance
    clearance = effective_clearance(role, department)

    return UserContext(
        user_id=user_id,
        role=role,
        department=department,
        clearance_level=clearance,
    )


def make_dev_token(
    user_id: str,
    role: str,
    department: str = "all",
    expires_in_hours: int = 8,
) -> str:
    """
    Generate a short-lived JWT for dev/testing.
    Never use in production — always use a real auth server.
    """
    secret = os.getenv("JWT_SECRET", "dev-secret-change-me")
    exp    = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)

    try:
        import jwt
        return jwt.encode(
            {"sub": user_id, "role": role, "dept": department, "exp": exp},
            secret,
            algorithm="HS256",
        )
    except ImportError:
        raise RuntimeError("pip install PyJWT to use jwt_auth")
