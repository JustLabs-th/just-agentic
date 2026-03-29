"""Tests for tools/_tool_client.py — HTTP routing layer to Tool Service."""

import pytest
import requests


class TestIsEnabled:
    def test_is_enabled_false_when_url_not_set(self, monkeypatch):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "")
        assert tc.is_enabled() is False

    def test_is_enabled_true_when_url_set(self, monkeypatch):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        assert tc.is_enabled() is True

    def test_is_enabled_false_for_whitespace_url(self, monkeypatch):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "")
        assert tc.is_enabled() is False


class TestCall:
    def test_call_returns_none_when_url_not_set(self, monkeypatch):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "")
        result = tc.call("run_shell", {"command": "echo hi"})
        assert result is None

    def test_call_posts_to_correct_url(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"output": "STDOUT:\nhello\nEXIT CODE: 0"}
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        tc.call("run_shell", {"command": "echo hello"}, workspace="/app", timeout=60)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://tool-service:8001/execute"

    def test_call_sends_correct_payload(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"output": "done"}
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        tc.call("execute_python", {"code": "print(1)"}, workspace="/tmp", timeout=30)

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["tool"] == "execute_python"
        assert payload["inputs"] == {"code": "print(1)"}
        assert payload["workspace"] == "/tmp"
        assert payload["timeout"] == 30

    def test_call_includes_auth_header_when_secret_set(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "mysecret")

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"output": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        tc.call("run_shell", {"command": "ls"})

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer mysecret"

    def test_call_no_auth_header_when_no_secret(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"output": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        tc.call("run_shell", {"command": "ls"})

        call_kwargs = mock_post.call_args[1]
        assert "Authorization" not in call_kwargs.get("headers", {})

    def test_call_returns_output_string_on_success(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"output": "STDOUT:\nhello\nEXIT CODE: 0"}
        mock_resp.raise_for_status.return_value = None
        mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        result = tc.call("run_shell", {"command": "echo hello"})
        assert result == "STDOUT:\nhello\nEXIT CODE: 0"

    def test_call_returns_error_string_on_connection_error(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mocker.patch(
            "tools._tool_client.requests.post",
            side_effect=requests.ConnectionError("refused"),
        )

        result = tc.call("run_shell", {"command": "ls"})
        assert result is not None
        assert "ERROR" in result
        assert "tool-service:8001" in result

    def test_call_returns_error_string_on_http_401(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mock_resp = mocker.Mock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"detail": "Unauthorized"}
        http_error = requests.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_error
        mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        result = tc.call("run_shell", {"command": "ls"})
        assert result is not None
        assert "ERROR" in result
        assert "401" in result

    def test_call_returns_error_string_on_http_500(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mock_resp = mocker.Mock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"detail": "Internal Server Error"}
        http_error = requests.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_error
        mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        result = tc.call("run_shell", {"command": "ls"})
        assert result is not None
        assert "ERROR" in result
        assert "500" in result

    def test_call_returns_timeout_error_string_on_requests_timeout(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mocker.patch(
            "tools._tool_client.requests.post",
            side_effect=requests.Timeout(),
        )

        result = tc.call("run_shell", {"command": "sleep 60"}, timeout=60)
        assert result is not None
        assert "ERROR" in result
        assert "70" in result  # timeout + _OVERHEAD_S (10)

    def test_call_request_timeout_includes_overhead(self, monkeypatch, mocker):
        import tools._tool_client as tc
        monkeypatch.setattr(tc, "_SERVICE_URL", "http://tool-service:8001")
        monkeypatch.setattr(tc, "_SERVICE_SECRET", "")

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"output": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("tools._tool_client.requests.post", return_value=mock_resp)

        tc.call("run_shell", {"command": "ls"}, timeout=60)

        call_kwargs = mock_post.call_args[1]
        # Should be tool timeout (60) + overhead (10) = 70
        assert call_kwargs["timeout"] == 70
