"""Tests for RBAC role + department policies."""

import pytest
from security.rbac import (
    Clearance,
    get_policy,
    get_department_policy,
    effective_tools,
    effective_clearance,
    is_tool_allowed,
    ROLES,
    DEPARTMENTS,
)


# ── Role policies ──────────────────────────────────────────────────────────

class TestRoles:
    def test_all_roles_exist(self):
        for role in ("viewer", "analyst", "manager", "admin"):
            assert get_policy(role) is not None

    def test_unknown_role_raises(self):
        with pytest.raises(PermissionError, match="Unknown role"):
            get_policy("superadmin")

    def test_viewer_clearance(self):
        assert get_policy("viewer").clearance_ceiling == Clearance.PUBLIC

    def test_analyst_clearance(self):
        assert get_policy("analyst").clearance_ceiling == Clearance.INTERNAL

    def test_manager_clearance(self):
        assert get_policy("manager").clearance_ceiling == Clearance.CONFIDENTIAL

    def test_admin_clearance(self):
        assert get_policy("admin").clearance_ceiling == Clearance.SECRET

    def test_viewer_cannot_write(self):
        assert "write_file" not in get_policy("viewer").allowed_tools

    def test_admin_can_write(self):
        assert "write_file" in get_policy("admin").allowed_tools

    def test_viewer_tools_are_subset_of_admin(self):
        viewer_tools = get_policy("viewer").allowed_tools
        admin_tools  = get_policy("admin").allowed_tools
        assert viewer_tools.issubset(admin_tools)

    def test_role_clearance_is_monotonic(self):
        """Higher roles must have >= clearance."""
        levels = [get_policy(r).clearance_ceiling for r in ("viewer", "analyst", "manager", "admin")]
        assert levels == sorted(levels)


# ── Department policies ────────────────────────────────────────────────────

class TestDepartments:
    def test_all_departments_exist(self):
        for dept in ("engineering", "devops", "qa", "data", "security", "all"):
            assert get_department_policy(dept) is not None

    def test_unknown_department_raises(self):
        with pytest.raises(PermissionError, match="Unknown department"):
            get_department_policy("finance")

    def test_qa_dept_excludes_write_file(self):
        assert "write_file" not in get_department_policy("qa").permitted_tools

    def test_engineering_dept_includes_write_file(self):
        assert "write_file" in get_department_policy("engineering").permitted_tools

    def test_qa_max_clearance_is_internal(self):
        assert get_department_policy("qa").max_clearance == Clearance.INTERNAL

    def test_security_dept_max_clearance_is_secret(self):
        assert get_department_policy("security").max_clearance == Clearance.SECRET


# ── Effective tools (role ∩ dept) ──────────────────────────────────────────

class TestEffectiveTools:
    def test_admin_qa_excludes_write_file(self):
        """admin role has write_file, but qa dept does not — result excludes it."""
        tools = effective_tools("admin", "qa")
        assert "write_file" not in tools

    def test_admin_engineering_includes_write_file(self):
        tools = effective_tools("admin", "engineering")
        assert "write_file" in tools

    def test_viewer_engineering_still_cannot_write(self):
        """viewer role lacks write_file — even engineering dept cannot grant it."""
        tools = effective_tools("viewer", "engineering")
        assert "write_file" not in tools

    def test_effective_tools_is_subset_of_role_tools(self):
        role_tools = get_policy("manager").allowed_tools
        dept_tools = effective_tools("manager", "devops")
        assert dept_tools.issubset(role_tools)

    def test_effective_tools_is_subset_of_dept_tools(self):
        dept_tools = get_department_policy("qa").permitted_tools
        eff_tools  = effective_tools("admin", "qa")
        assert eff_tools.issubset(dept_tools)

    def test_all_dept_does_not_expand_role(self):
        """dept='all' should not grant more tools than the role allows."""
        viewer_role_tools = get_policy("viewer").allowed_tools
        eff = effective_tools("viewer", "all")
        assert eff == viewer_role_tools


# ── Effective clearance: min(role, dept) ──────────────────────────────────

class TestEffectiveClearance:
    def test_admin_in_qa_capped_at_internal(self):
        assert effective_clearance("admin", "qa") == Clearance.INTERNAL

    def test_viewer_in_security_dept_still_public(self):
        """dept cannot raise role clearance."""
        assert effective_clearance("viewer", "security") == Clearance.PUBLIC

    def test_admin_in_security_is_secret(self):
        assert effective_clearance("admin", "security") == Clearance.SECRET

    def test_analyst_in_data_is_internal(self):
        """analyst ceiling=INTERNAL, data ceiling=SECRET → min = INTERNAL."""
        assert effective_clearance("analyst", "data") == Clearance.INTERNAL


# ── is_tool_allowed (role ∩ dept) ─────────────────────────────────────────

class TestIsToolAllowed:
    def test_viewer_cannot_run_shell(self):
        assert is_tool_allowed("viewer", "run_shell", "engineering") is False

    def test_manager_can_run_shell(self):
        assert is_tool_allowed("manager", "run_shell", "engineering") is True

    def test_unknown_role_returns_false(self):
        assert is_tool_allowed("ghost", "read_file", "engineering") is False
