"""Tests for tool_service/main.py — FastAPI endpoint via TestClient."""

import importlib

import pytest
from fastapi.testclient import TestClient


def _get_client(secret: str = "") -> TestClient:
    """
    Import (or reload) tool_service.main with _SECRET patched to `secret`,
    then return a TestClient around the app.

    We patch the module-level `_SECRET` directly because FastAPI reads it at
    request time via the closure in `_verify_auth`, so patching after import
    is sufficient — no reload required.
    """
    import tool_service.main as svc_main
    svc_main._SECRET = secret
    return TestClient(svc_main.app)


class TestHealthz:
    def test_healthz_returns_ok(self):
        client = _get_client()
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestExecuteRunShell:
    def test_run_shell_returns_output_structure(self):
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "run_shell",
            "inputs": {"command": "echo hello"},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "output" in body
        assert "hello" in body["output"]
        assert "EXIT CODE:" in body["output"]

    def test_run_shell_missing_command_returns_400(self):
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "run_shell",
            "inputs": {},
        })
        assert resp.status_code == 400

    def test_run_shell_non_zero_exit_captured(self):
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "run_shell",
            "inputs": {"command": "exit 1"},
        })
        assert resp.status_code == 200
        assert "EXIT CODE: 1" in resp.json()["output"]


class TestExecutePython:
    def test_execute_python_runs_code(self):
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "execute_python",
            "inputs": {"code": "print('from python')"},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "output" in body
        assert "from python" in body["output"]

    def test_execute_python_missing_code_returns_400(self):
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "execute_python",
            "inputs": {},
        })
        assert resp.status_code == 400

    def test_execute_python_timeout_capped_at_30(self):
        # Timeout > 30 should still be accepted (capped internally)
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "execute_python",
            "inputs": {"code": "print('capped')"},
            "timeout": 120,
        })
        assert resp.status_code == 200
        assert "capped" in resp.json()["output"]


class TestExecuteRunTests:
    def test_run_tests_executes_command(self):
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "run_tests",
            "inputs": {"command": "echo test-runner-output"},
        })
        assert resp.status_code == 200
        assert "test-runner-output" in resp.json()["output"]

    def test_run_tests_uses_default_command_when_empty(self):
        # inputs without "command" key → defaults to "pytest -q"
        # we just verify it runs and returns output (not checking pass/fail)
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "run_tests",
            "inputs": {},
        })
        assert resp.status_code == 200
        assert "output" in resp.json()


class TestExecuteUnknownTool:
    def test_unknown_tool_returns_400(self):
        client = _get_client()
        resp = client.post("/execute", json={
            "tool": "not_a_real_tool",
            "inputs": {},
        })
        assert resp.status_code == 400
        assert "not_a_real_tool" in resp.json()["detail"]


class TestExecuteMissingField:
    def test_missing_tool_field_returns_422(self):
        client = _get_client()
        resp = client.post("/execute", json={"inputs": {}})
        assert resp.status_code == 422

    def test_missing_inputs_field_returns_422(self):
        client = _get_client()
        resp = client.post("/execute", json={"tool": "run_shell"})
        assert resp.status_code == 422

    def test_empty_body_returns_422(self):
        client = _get_client()
        resp = client.post("/execute", json={})
        assert resp.status_code == 422


class TestAuth:
    def test_correct_bearer_token_returns_200(self):
        client = _get_client(secret="supersecret")
        resp = client.post(
            "/execute",
            json={"tool": "run_shell", "inputs": {"command": "echo ok"}},
            headers={"Authorization": "Bearer supersecret"},
        )
        assert resp.status_code == 200

    def test_wrong_bearer_token_returns_401(self):
        client = _get_client(secret="supersecret")
        resp = client.post(
            "/execute",
            json={"tool": "run_shell", "inputs": {"command": "echo ok"}},
            headers={"Authorization": "Bearer wrongtoken"},
        )
        assert resp.status_code == 401

    def test_missing_authorization_header_returns_401(self):
        client = _get_client(secret="supersecret")
        resp = client.post(
            "/execute",
            json={"tool": "run_shell", "inputs": {"command": "echo ok"}},
        )
        assert resp.status_code == 401

    def test_bearer_prefix_required(self):
        client = _get_client(secret="supersecret")
        resp = client.post(
            "/execute",
            json={"tool": "run_shell", "inputs": {"command": "echo ok"}},
            headers={"Authorization": "supersecret"},
        )
        assert resp.status_code == 401

    def test_no_secret_configured_accepts_any_request(self):
        # When _SECRET is empty string, open mode — no auth enforced
        client = _get_client(secret="")
        resp = client.post(
            "/execute",
            json={"tool": "run_shell", "inputs": {"command": "echo open"}},
        )
        assert resp.status_code == 200

    def test_no_secret_configured_no_header_still_200(self):
        client = _get_client(secret="")
        resp = client.post(
            "/execute",
            json={"tool": "run_shell", "inputs": {"command": "echo noauth"}},
        )
        assert resp.status_code == 200

    def test_healthz_never_requires_auth(self):
        client = _get_client(secret="topsecret")
        resp = client.get("/healthz")
        assert resp.status_code == 200
