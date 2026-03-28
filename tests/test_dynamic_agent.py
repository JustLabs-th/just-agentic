"""Tests for dynamic agent node factory."""

import pytest
from unittest.mock import MagicMock, patch


def _state(agent_definitions=None, allowed_agents=None):
    return {
        "messages": [],
        "user_id": "alice",
        "user_role": "analyst",
        "user_department": "engineering",
        "clearance_level": 2,
        "allowed_tools": ["read_file", "list_files"],
        "allowed_agents": allowed_agents or ["custom_bot"],
        "agent_definitions": agent_definitions or [
            {
                "name": "custom_bot",
                "display_name": "Custom Bot",
                "system_prompt": "You are a custom bot.",
                "allowed_tools": ["read_file"],
                "department": "engineering",
            }
        ],
        "goal_for_agent": "Read the readme",
        "tools_called": [],
        "status": "working",
    }


class TestDynamicAgentNode:
    def test_missing_definition_returns_error(self):
        from graph.agents.dynamic import dynamic_agent_node
        node = dynamic_agent_node("ghost_agent")
        result = node(_state(agent_definitions=[]))  # ghost_agent not in definitions
        assert result["status"] == "error"
        assert result["current_agent"] == "ghost_agent"

    def test_sets_current_agent_name(self):
        from graph.agents.dynamic import dynamic_agent_node
        node = dynamic_agent_node("custom_bot")

        fake_result = {"messages": [MagicMock(content="done")]}
        with patch("graph.agents.dynamic.create_react_agent") as mock_agent, \
             patch("graph.agents.dynamic.set_role_context"), \
             patch("graph.agents.dynamic.set_tool_context"), \
             patch("graph.agents.dynamic.get_adapter"), \
             patch("graph.agents.dynamic.extract_tools_called", return_value=[]):
            mock_agent.return_value.invoke.return_value = fake_result
            result = node(_state())

        assert result["current_agent"] == "custom_bot"

    def test_filters_tools_by_definition_allowed_tools(self):
        """Only tools in agent_definitions[*].allowed_tools are passed to create_react_agent."""
        from graph.agents.dynamic import dynamic_agent_node
        node = dynamic_agent_node("custom_bot")

        captured_tools = []
        fake_result = {"messages": [MagicMock(content="done")]}

        def capture_agent(model, tools, prompt):
            captured_tools.extend([t.name for t in tools])
            m = MagicMock()
            m.invoke.return_value = fake_result
            return m

        with patch("graph.agents.dynamic.create_react_agent", side_effect=capture_agent), \
             patch("graph.agents.dynamic.set_role_context"), \
             patch("graph.agents.dynamic.set_tool_context"), \
             patch("graph.agents.dynamic.get_adapter"), \
             patch("graph.agents.dynamic.extract_tools_called", return_value=[]):
            node(_state())

        # custom_bot only has read_file in allowed_tools
        assert "read_file" in captured_tools
        assert "list_files" not in captured_tools

    def test_empty_tools_returns_permission_denied_message(self):
        from graph.agents.dynamic import dynamic_agent_node
        node = dynamic_agent_node("custom_bot")
        state = _state(agent_definitions=[{
            "name": "custom_bot",
            "display_name": "Custom Bot",
            "system_prompt": "You are a custom bot.",
            "allowed_tools": [],  # no tools
            "department": "engineering",
        }])
        result = node(state)
        assert result["status"] == "done"
        assert "Permission denied" in result["messages"][-1].content

    def test_node_function_name_matches_agent_name(self):
        from graph.agents.dynamic import dynamic_agent_node
        node = dynamic_agent_node("my_agent")
        assert node.__name__ == "my_agent_node"
