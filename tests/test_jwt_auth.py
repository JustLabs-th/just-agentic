"""
Tests for JWT authentication — decode_token, make_dev_token, rbac_guard JWT path.
"""

import os
import time
import pytest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

# Ensure JWT_SECRET is set for all tests
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest")


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_token(payload_overrides: dict | None = None, secret: str = "test-secret-for-pytest") -> str:
    import jwt
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {"sub": "alice", "role": "analyst", "dept": "engineering", "exp": exp}
    if payload_overrides:
        payload.update(payload_overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


# ── decode_token ──────────────────────────────────────────────────────────────

class TestDecodeToken:
    def test_valid_token_returns_user_context(self):
        from security.jwt_auth import decode_token
        token = _make_token()
        ctx = decode_token(token)
        assert ctx.user_id == "alice"
        assert ctx.role == "analyst"
        assert ctx.department == "engineering"
        assert ctx.clearance_level > 0

    def test_missing_dept_claim_raises(self):
        """dept is a required claim — token without it is rejected."""
        from security.jwt_auth import decode_token
        import jwt
        exp = datetime.now(timezone.utc) + timedelta(hours=1)
        raw = jwt.encode({"sub": "alice", "role": "analyst", "exp": exp},
                         "test-secret-for-pytest", algorithm="HS256")
        with pytest.raises(ValueError):
            decode_token(raw)

    def test_expired_token_raises(self):
        from security.jwt_auth import decode_token
        import jwt
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        token = jwt.encode({"sub": "alice", "role": "analyst", "exp": past},
                           "test-secret-for-pytest", algorithm="HS256")
        with pytest.raises(ValueError, match="expired"):
            decode_token(token)

    def test_wrong_secret_raises(self):
        from security.jwt_auth import decode_token
        token = _make_token(secret="other-secret")
        with pytest.raises(ValueError):
            decode_token(token)

    def test_missing_sub_raises(self):
        from security.jwt_auth import decode_token
        import jwt
        exp = datetime.now(timezone.utc) + timedelta(hours=1)
        token = jwt.encode({"role": "analyst", "exp": exp},
                           "test-secret-for-pytest", algorithm="HS256")
        with pytest.raises(ValueError):
            decode_token(token)

    def test_unknown_role_raises(self):
        from security.jwt_auth import decode_token
        token = _make_token({"role": "overlord"})
        with pytest.raises((ValueError, PermissionError)):
            decode_token(token)

    def test_unknown_department_raises(self):
        from security.jwt_auth import decode_token
        token = _make_token({"dept": "narnia"})
        with pytest.raises((ValueError, PermissionError)):
            decode_token(token)

    def test_no_jwt_secret_raises_runtime_error(self):
        from security.jwt_auth import decode_token
        token = _make_token()
        with patch.dict(os.environ, {"JWT_SECRET": ""}):
            with pytest.raises(RuntimeError, match="JWT_SECRET"):
                decode_token(token)


# ── make_dev_token ────────────────────────────────────────────────────────────

class TestMakeDevToken:
    def test_returns_string(self):
        from security.jwt_auth import make_dev_token
        token = make_dev_token("bob", "manager", "devops")
        assert isinstance(token, str)
        assert len(token) > 10

    def test_roundtrip_decode(self):
        from security.jwt_auth import make_dev_token, decode_token
        token = make_dev_token("bob", "manager", "devops")
        ctx = decode_token(token)
        assert ctx.user_id == "bob"
        assert ctx.role == "manager"
        assert ctx.department == "devops"

    def test_default_department_all(self):
        from security.jwt_auth import make_dev_token, decode_token
        token = make_dev_token("carol", "viewer")
        ctx = decode_token(token)
        assert ctx.department == "all"

    def test_token_expires(self):
        """Token made with expires_in_hours=0 should be expired immediately."""
        from security.jwt_auth import decode_token
        import jwt
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        token = jwt.encode({"sub": "x", "role": "viewer", "dept": "all", "exp": past},
                           os.environ["JWT_SECRET"], algorithm="HS256")
        with pytest.raises(ValueError):
            decode_token(token)

    def test_admin_role(self):
        from security.jwt_auth import make_dev_token, decode_token
        token = make_dev_token("admin_user", "admin", "security")
        ctx = decode_token(token)
        assert ctx.role == "admin"
        assert ctx.clearance_level >= 3   # SECRET or higher


# ── rbac_guard JWT path ───────────────────────────────────────────────────────

class TestRbacGuardJwtPath:
    def _base_state(self, jwt_token: str) -> dict:
        return {
            "messages": [],
            "jwt_token": jwt_token,
            "user_id": "",
            "user_role": "",
            "user_department": "",
            "clearance_level": 0,
            "allowed_tools": [],
            "status": "",
        }

    def test_valid_token_populates_state(self):
        from graph.nodes.rbac_guard import rbac_guard_node
        token = _make_token()
        result = rbac_guard_node(self._base_state(token))
        assert result["user_id"] == "alice"
        assert result["user_role"] == "analyst"
        assert result["user_department"] == "engineering"
        assert result["clearance_level"] > 0
        assert len(result["allowed_tools"]) > 0
        assert result["status"] == "ok"

    def test_invalid_token_denies(self):
        from graph.nodes.rbac_guard import rbac_guard_node
        result = rbac_guard_node(self._base_state("not.a.jwt"))
        assert result["status"] == "permission_denied"
        assert result["allowed_tools"] == []

    def test_expired_token_denies(self):
        from graph.nodes.rbac_guard import rbac_guard_node
        import jwt
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        token = jwt.encode({"sub": "alice", "role": "analyst", "exp": past},
                           "test-secret-for-pytest", algorithm="HS256")
        result = rbac_guard_node(self._base_state(token))
        assert result["status"] == "permission_denied"

    def test_plain_mode_still_works(self):
        """Plain dev credentials path (no jwt_token) should remain functional."""
        from graph.nodes.rbac_guard import rbac_guard_node
        state = {
            "messages": [],
            "jwt_token": "",
            "user_id": "dev_user",
            "user_role": "analyst",
            "user_department": "engineering",
            "clearance_level": 0,
            "allowed_tools": [],
            "status": "",
        }
        result = rbac_guard_node(state)
        assert result["status"] == "ok"
        assert result["user_role"] == "analyst"

    def test_admin_token_has_full_tools(self):
        from graph.nodes.rbac_guard import rbac_guard_node
        from security.jwt_auth import make_dev_token
        token = make_dev_token("superuser", "admin", "security")
        result = rbac_guard_node(self._base_state(token))
        assert result["status"] == "ok"
        assert len(result["allowed_tools"]) >= 5
