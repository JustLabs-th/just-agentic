"""Tests for department guard node."""

import pytest
from langchain_core.messages import AIMessage
from graph.nodes.department_guard import department_guard_node
from security.output_classifier import Clearance


def _state(role: str, department: str, allowed_tools: list[str] | None = None,
           clearance: int = 4) -> dict:
    return {
        "user_role":       role,
        "user_department": department,
        "allowed_tools":   allowed_tools or [],
        "clearance_level": clearance,
        "status":          "",
    }


class TestDepartmentGuardReducesTools:
    def test_admin_qa_excludes_write_file(self):
        state  = _state("admin", "qa", allowed_tools=["write_file", "read_file", "run_tests"])
        result = department_guard_node(state)
        assert "write_file" not in result["allowed_tools"]

    def test_admin_engineering_keeps_write_file(self):
        state  = _state("admin", "engineering", allowed_tools=["write_file", "read_file"])
        result = department_guard_node(state)
        assert "write_file" in result["allowed_tools"]

    def test_viewer_tools_unchanged_in_all_dept(self):
        viewer_tools = ["read_file", "list_files", "web_search"]
        state  = _state("viewer", "all", allowed_tools=viewer_tools, clearance=1)
        result = department_guard_node(state)
        assert set(result["allowed_tools"]) == set(viewer_tools)


class TestDepartmentGuardReducesClearance:
    def test_admin_in_qa_capped_at_internal(self):
        state  = _state("admin", "qa", clearance=Clearance.SECRET)
        result = department_guard_node(state)
        assert result["clearance_level"] == Clearance.INTERNAL

    def test_viewer_in_security_stays_public(self):
        """Department cannot raise clearance beyond role ceiling."""
        state  = _state("viewer", "security", clearance=Clearance.PUBLIC)
        result = department_guard_node(state)
        assert result["clearance_level"] == Clearance.PUBLIC

    def test_admin_in_security_stays_secret(self):
        state  = _state("admin", "security", clearance=Clearance.SECRET)
        result = department_guard_node(state)
        assert result["clearance_level"] == Clearance.SECRET


class TestDepartmentGuardBlocking:
    def test_unknown_department_denied(self):
        state  = _state("admin", "finance")
        result = department_guard_node(state)
        assert result["status"] == "permission_denied"
        assert result["allowed_tools"] == []

    def test_unknown_department_returns_ai_message(self):
        state  = _state("admin", "finance")
        result = department_guard_node(state)
        last_msg = result["messages"][-1]
        assert isinstance(last_msg, AIMessage)


class TestDepartmentGuardPreservesDept:
    def test_user_department_set_in_output(self):
        state  = _state("manager", "devops")
        result = department_guard_node(state)
        assert result["user_department"] == "devops"
