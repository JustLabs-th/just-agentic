"""Tests for @permission_required decorator — role ∩ dept enforcement."""

import pytest
from tools._permission import set_role_context, get_role_context, permission_required


def _make_tool(name: str):
    """Create a simple mock tool function wrapped with @permission_required."""
    @permission_required(name)
    def tool_fn(*args, **kwargs):
        return "executed"
    return tool_fn


class TestPermissionRequired:
    def test_viewer_blocked_from_write_file(self):
        set_role_context("viewer", "engineering", 1)
        fn = _make_tool("write_file")
        result = fn()
        assert "PERMISSION DENIED" in result
        assert "write_file" in result

    def test_admin_engineering_allowed_write_file(self):
        set_role_context("admin", "engineering", 3)
        fn = _make_tool("write_file")
        assert fn() == "executed"

    def test_admin_qa_blocked_from_write_file(self):
        """admin role has write_file, but qa dept doesn't — must be blocked."""
        set_role_context("admin", "qa", 2)
        fn = _make_tool("write_file")
        result = fn()
        assert "PERMISSION DENIED" in result

    def test_admin_qa_blocked_from_run_shell(self):
        """qa dept does have run_shell — admin/qa should be allowed."""
        set_role_context("admin", "qa", 2)
        fn = _make_tool("run_shell")
        assert fn() == "executed"

    def test_viewer_blocked_from_run_shell(self):
        set_role_context("viewer", "all", 1)
        fn = _make_tool("run_shell")
        result = fn()
        assert "PERMISSION DENIED" in result

    def test_no_role_context_is_blocked(self):
        """Empty role = unauthenticated session — should fail closed."""
        set_role_context("", "all", 0)
        fn = _make_tool("write_file")
        result = fn()
        assert "PERMISSION DENIED" in result

    def test_error_message_includes_dept(self):
        set_role_context("analyst", "devops", 2)
        fn = _make_tool("write_file")
        result = fn()
        assert "analyst" in result
        assert "devops" in result

    def test_context_is_per_call(self):
        """Changing context between calls must take effect immediately."""
        set_role_context("viewer", "engineering", 1)
        fn = _make_tool("write_file")
        assert "PERMISSION DENIED" in fn()

        set_role_context("admin", "engineering", 3)
        assert fn() == "executed"


class TestSetRoleContext:
    def test_get_returns_what_was_set(self):
        set_role_context("manager", "devops", 3)
        role, dept, clearance = get_role_context()
        assert role == "manager"
        assert dept == "devops"
        assert clearance == 3

    def test_dept_defaults_to_all(self):
        set_role_context("admin")
        _, dept, _ = get_role_context()
        assert dept == "all"
