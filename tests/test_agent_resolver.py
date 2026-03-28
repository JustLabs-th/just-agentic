"""Tests for agent_resolver node — DB loading, RBAC floor, single_agent_mode."""

import pytest
from unittest.mock import MagicMock, patch


def _state(user_id="alice", allowed_tools=None):
    return {
        "messages": [],
        "user_id": user_id,
        "user_role": "analyst",
        "user_department": "engineering",
        "clearance_level": 2,
        "allowed_tools": allowed_tools or ["read_file", "list_files", "web_search", "search_code"],
        "status": "ok",
    }


def _mock_defn(name, tools, is_default=False, is_active=True):
    d = MagicMock()
    d.name = name
    d.display_name = f"{name.title()} Agent"
    d.system_prompt = f"You are {name}."
    d.allowed_tools = tools
    d.department = "engineering"
    d.is_default = is_default
    d.is_active = is_active
    return d


def _mock_binding(agent_definition_id):
    b = MagicMock()
    b.agent_definition_id = agent_definition_id
    b.is_active = True
    return b


# ── Binding-based resolution ──────────────────────────────────────────────────

class TestAgentResolverWithBindings:
    def _setup_db(self, db_mock, bindings, definitions):
        binding_query = MagicMock()
        binding_query.filter_by.return_value.all.return_value = bindings

        def_query = MagicMock()
        def_query.filter.return_value.all.return_value = definitions

        db_mock.query.side_effect = lambda model: (
            binding_query if "UserAgentBinding" in str(model) else def_query
        )

    def test_returns_bound_agents(self):
        from graph.nodes.agent_resolver import agent_resolver_node
        defn = _mock_defn("backend", ["read_file", "write_file"])
        binding = _mock_binding(defn.id)

        with patch("db.session.get_db") as mock_ctx, \
             patch("db.models.UserAgentBinding"), \
             patch("db.models.AgentDefinition"):
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            db.query.return_value.filter_by.return_value.all.side_effect = [
                [binding], [defn]
            ]
            db.query.return_value.filter.return_value.all.return_value = [defn]

            result = agent_resolver_node(_state())
            assert "backend" in result["allowed_agents"]

    def test_rbac_floor_intersects_tools(self):
        """Agent has write_file but user RBAC doesn't — must be stripped."""
        from graph.nodes.agent_resolver import agent_resolver_node
        defn = _mock_defn("backend", ["read_file", "write_file"])
        state = _state(allowed_tools=["read_file"])  # write_file NOT in RBAC

        with patch("db.session.get_db") as mock_ctx, \
             patch("db.models.UserAgentBinding"), \
             patch("db.models.AgentDefinition"):
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            db.query.return_value.filter_by.return_value.all.side_effect = [
                [_mock_binding(1)], [defn]
            ]
            db.query.return_value.filter.return_value.all.return_value = [defn]

            result = agent_resolver_node(state)
            backend_def = next(d for d in result["agent_definitions"] if d["name"] == "backend")
            assert "write_file" not in backend_def["allowed_tools"]
            assert "read_file" in backend_def["allowed_tools"]

    def test_no_tool_overlap_still_included(self):
        """Agent with zero overlap tools stays in allowed_agents but has empty tool list."""
        from graph.nodes.agent_resolver import agent_resolver_node
        defn = _mock_defn("backend", ["write_file", "run_shell"])
        state = _state(allowed_tools=["web_search"])  # no overlap

        with patch("db.session.get_db") as mock_ctx, \
             patch("db.models.UserAgentBinding"), \
             patch("db.models.AgentDefinition"):
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            db.query.return_value.filter_by.return_value.all.side_effect = [
                [_mock_binding(1)], [defn]
            ]
            db.query.return_value.filter.return_value.all.return_value = [defn]

            result = agent_resolver_node(state)
            assert "backend" in result["allowed_agents"]
            backend_def = next(d for d in result["agent_definitions"] if d["name"] == "backend")
            assert backend_def["allowed_tools"] == []

    def test_single_agent_mode_true_when_one_binding(self):
        from graph.nodes.agent_resolver import agent_resolver_node
        defn = _mock_defn("backend", ["read_file"])

        with patch("db.session.get_db") as mock_ctx, \
             patch("db.models.UserAgentBinding"), \
             patch("db.models.AgentDefinition"):
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            db.query.return_value.filter_by.return_value.all.side_effect = [
                [_mock_binding(1)], [defn]
            ]
            db.query.return_value.filter.return_value.all.return_value = [defn]

            result = agent_resolver_node(_state())
            assert result["single_agent_mode"] is True

    def test_single_agent_mode_false_when_multiple(self):
        from graph.nodes.agent_resolver import agent_resolver_node
        defn1 = _mock_defn("backend", ["read_file"])
        defn2 = _mock_defn("qa", ["read_file"])
        defn2.id = 2

        with patch("db.session.get_db") as mock_ctx, \
             patch("db.models.UserAgentBinding"), \
             patch("db.models.AgentDefinition"):
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            db.query.return_value.filter_by.return_value.all.side_effect = [
                [_mock_binding(1), _mock_binding(2)], [defn1, defn2]
            ]
            db.query.return_value.filter.return_value.all.return_value = [defn1, defn2]

            result = agent_resolver_node(_state())
            assert result["single_agent_mode"] is False


# ── Default fallback ──────────────────────────────────────────────────────────

class TestAgentResolverFallback:
    def test_falls_back_to_defaults_when_no_bindings(self):
        from graph.nodes.agent_resolver import agent_resolver_node
        defn = _mock_defn("backend", ["read_file"], is_default=True)

        with patch("db.session.get_db") as mock_ctx, \
             patch("db.models.UserAgentBinding"), \
             patch("db.models.AgentDefinition"):
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            # No user bindings
            db.query.return_value.filter_by.return_value.all.side_effect = [
                [], [defn]
            ]

            result = agent_resolver_node(_state())
            assert "backend" in result["allowed_agents"]


# ── DB failure ────────────────────────────────────────────────────────────────

class TestAgentResolverFailure:
    def test_db_failure_returns_permission_denied(self):
        from graph.nodes.agent_resolver import agent_resolver_node

        cm = MagicMock()
        cm.__enter__ = MagicMock(side_effect=Exception("DB down"))
        cm.__exit__ = MagicMock(return_value=False)

        with patch("db.session.get_db", return_value=cm):
            result = agent_resolver_node(_state())
            assert result["status"] == "permission_denied"
            assert result["allowed_agents"] == []
            assert result["single_agent_mode"] is False
