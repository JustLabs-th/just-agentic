"""Tests for supervisor routing logic — loop detection, fallback, iteration cap, ABAC."""

import pytest
from graph.supervisor import _parse_decision, MAX_ITERATIONS

_DEFAULT_AGENTS = {"backend", "devops", "qa"}


class TestParseDecision:
    def test_valid_json_parsed(self):
        raw = '{"next_agent": "devops", "intent": "infrastructure_write", "confidence": 0.9, "reason": "Docker task", "goal_for_agent": "Create Dockerfile", "done": false}'
        d = _parse_decision(raw, _DEFAULT_AGENTS)
        assert d["next_agent"]   == "devops"
        assert d["intent"]       == "infrastructure_write"
        assert d["confidence"]   == 0.9
        assert d["done"]         is False

    def test_json_in_markdown_code_block(self):
        raw = '```json\n{"next_agent": "backend", "intent": "code_read", "confidence": 0.8, "reason": "x", "goal_for_agent": "y", "done": false}\n```'
        d = _parse_decision(raw, _DEFAULT_AGENTS)
        assert d["next_agent"] == "backend"

    def test_unknown_agent_sets_done_true(self):
        raw = '{"next_agent": "unknown_agent", "intent": "x", "confidence": 0.5, "reason": "", "goal_for_agent": "", "done": false}'
        d = _parse_decision(raw, _DEFAULT_AGENTS)
        assert d["done"] is True

    def test_finish_agent_sets_done_true(self):
        raw = '{"next_agent": "finish", "intent": "info_request", "confidence": 0.95, "reason": "done", "goal_for_agent": "answer", "done": false}'
        d = _parse_decision(raw, _DEFAULT_AGENTS)
        assert d["done"] is True

    def test_invalid_json_falls_back_to_keyword_scan(self):
        d = _parse_decision("I think devops should handle this Docker issue", _DEFAULT_AGENTS)
        assert d["next_agent"] == "devops"
        assert d["done"]       is False

    def test_completely_unparseable_returns_done(self):
        d = _parse_decision("I have no idea what to do here", _DEFAULT_AGENTS)
        assert d["done"] is True

    def test_confidence_clamped_to_0_1(self):
        raw = '{"next_agent": "qa", "intent": "test_run", "confidence": 1.5, "reason": "", "goal_for_agent": "", "done": false}'
        d = _parse_decision(raw, _DEFAULT_AGENTS)
        assert d["confidence"] <= 1.0

    def test_confidence_clamped_below_zero(self):
        raw = '{"next_agent": "qa", "intent": "test_run", "confidence": -0.5, "reason": "", "goal_for_agent": "", "done": false}'
        d = _parse_decision(raw, _DEFAULT_AGENTS)
        assert d["confidence"] >= 0.0

    def test_agent_outside_allowed_list_sets_done(self):
        """LLM returns 'backend' but user only has access to 'custom_bot'."""
        raw = '{"next_agent": "backend", "intent": "code_read", "confidence": 0.9, "reason": "", "goal_for_agent": "", "done": false}'
        d = _parse_decision(raw, {"custom_bot"})
        assert d["done"] is True

    def test_keyword_scan_uses_dynamic_valid_agents(self):
        raw = "I think custom_bot should handle this"
        d = _parse_decision(raw, {"custom_bot"})
        assert d["next_agent"] == "custom_bot"
        assert d["done"] is False


class TestLoopDetection:
    def _base_state(self, routing_history, iteration=3):
        return {
            "messages":          [],
            "user_goal":         "fix docker",
            "user_role":         "admin",
            "user_department":   "devops",
            "allowed_tools":     ["run_shell", "read_file"],
            "allowed_agents":    ["devops"],
            "agent_definitions": [{"name": "devops", "display_name": "DevOps", "system_prompt": "x", "allowed_tools": ["run_shell"]}],
            "single_agent_mode": False,
            "iteration":         iteration,
            "routing_history":   routing_history,
            "retry_count":       {},
            "supervisor_log":    [],
            "status":            "working",
            "plan":              [],
            "working_memory":    {},
        }

    def test_same_agent_three_times_triggers_loop(self):
        from graph.supervisor import supervisor_node, LOOP_WINDOW
        state = self._base_state(["devops"] * LOOP_WINDOW)
        result = supervisor_node(state)
        assert result["status"] in ("done", "error")
        assert "routing_loop" in result.get("error", "")

    def test_max_iterations_stops_graph(self):
        from graph.supervisor import supervisor_node
        state = self._base_state([], iteration=MAX_ITERATIONS)
        result = supervisor_node(state)
        assert result["status"] in ("done", "error")
        assert "max_iterations" in result.get("error", "")


class TestSingleAgentMode:
    def _base_state(self, agent_name="custom_bot"):
        return {
            "messages":          [],
            "user_goal":         "do the task",
            "user_role":         "analyst",
            "user_department":   "engineering",
            "allowed_tools":     ["read_file"],
            "allowed_agents":    [agent_name],
            "agent_definitions": [{"name": agent_name, "display_name": "Bot", "system_prompt": "x", "allowed_tools": ["read_file"]}],
            "single_agent_mode": True,
            "iteration":         0,
            "routing_history":   [],
            "retry_count":       {},
            "supervisor_log":    [],
            "status":            "working",
            "plan":              [],
            "working_memory":    {},
        }

    def test_single_agent_mode_skips_llm_on_first_turn(self):
        """When single_agent_mode=True and routing_history is empty, routes directly."""
        from graph.supervisor import supervisor_node
        from unittest.mock import patch

        with patch("graph.supervisor.get_adapter") as mock_adapter:
            result = supervisor_node(self._base_state())
            # LLM should NOT be called
            mock_adapter.assert_not_called()

        assert result["current_agent"] == "custom_bot"
        assert result["intent"] == "direct_route"
        assert result["confidence"] == 1.0

    def test_single_agent_mode_off_after_first_turn(self):
        """After first routing, supervisor runs normally (routing_history not empty)."""
        from graph.supervisor import supervisor_node
        from unittest.mock import patch

        state = self._base_state()
        state["routing_history"] = ["custom_bot"]  # already routed once
        state["single_agent_mode"] = True

        with patch("graph.supervisor.get_adapter") as mock_adapter:
            mock_invoke = mock_adapter.return_value.invoke
            mock_invoke.return_value = '{"next_agent": "finish", "intent": "info_request", "confidence": 0.9, "reason": "done", "goal_for_agent": "done", "done": true}'
            supervisor_node(state)
            mock_adapter.assert_called()
