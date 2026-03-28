"""Tests for tool output classification."""

import pytest
from security.output_classifier import Clearance
from security.output_classifier import (
    classify_path,
    classify_content,
    check_output_clearance,
)


class TestClassifyPath:
    @pytest.mark.parametrize("path, expected", [
        (".env",                  Clearance.CONFIDENTIAL),
        (".env.production",       Clearance.CONFIDENTIAL),
        ("config/.env",           Clearance.CONFIDENTIAL),
        ("secrets/key.pem",       Clearance.SECRET),
        ("certs/server.key",      Clearance.SECRET),
        ("backup.p12",            Clearance.SECRET),
        ("credentials.json",      Clearance.CONFIDENTIAL),
        ("api_keys.txt",          Clearance.CONFIDENTIAL),
        ("config/settings.py",    Clearance.INTERNAL),
        ("config/app.yaml",       Clearance.INTERNAL),
        ("docker-compose.yml",    Clearance.INTERNAL),
        ("main.py",               Clearance.PUBLIC),
        ("README.md",             Clearance.PUBLIC),
        ("requirements.txt",      Clearance.PUBLIC),
    ])
    def test_path_classification(self, path, expected):
        assert classify_path(path) == expected


class TestClassifyContent:
    def test_private_key_is_secret(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA..."
        assert classify_content(content) == Clearance.SECRET

    def test_openssh_key_is_secret(self):
        content = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk..."
        assert classify_content(content) == Clearance.SECRET

    def test_password_in_content_is_confidential(self):
        assert classify_content("password = 'mysecret123'") == Clearance.CONFIDENTIAL
        assert classify_content('api_key="sk-abc123456789"') == Clearance.CONFIDENTIAL
        assert classify_content("token=Bearer eyJhbGciOiJIUzI1NiJ9") == Clearance.CONFIDENTIAL

    def test_normal_code_is_public(self):
        assert classify_content("def hello():\n    return 'world'") == Clearance.PUBLIC

    def test_empty_content_is_public(self):
        assert classify_content("") == Clearance.PUBLIC


class TestCheckOutputClearance:
    def test_env_file_blocked_for_viewer(self):
        result = check_output_clearance(".env", "API_KEY=secret", Clearance.PUBLIC)
        assert result is not None
        assert "REDACTED" in result
        assert "CONFIDENTIAL" in result

    def test_env_file_allowed_for_manager(self):
        result = check_output_clearance(".env", "API_KEY=secret", Clearance.CONFIDENTIAL)
        assert result is None

    def test_private_key_blocked_for_manager(self):
        content = "-----BEGIN PRIVATE KEY-----\ndata"
        result = check_output_clearance("keys/server.key", content, Clearance.CONFIDENTIAL)
        assert result is not None
        assert "SECRET" in result

    def test_private_key_allowed_for_admin(self):
        content = "-----BEGIN PRIVATE KEY-----\ndata"
        result = check_output_clearance("keys/server.key", content, Clearance.SECRET)
        assert result is None

    def test_normal_file_always_allowed(self):
        result = check_output_clearance("main.py", "def hello(): pass", Clearance.PUBLIC)
        assert result is None

    def test_content_classification_takes_effect(self):
        """Normal path but content has a secret — must be blocked."""
        result = check_output_clearance(
            "notes.txt",
            "admin_password='hunter2'",
            Clearance.PUBLIC,
        )
        assert result is not None
        assert "REDACTED" in result

    def test_redaction_message_includes_path(self):
        result = check_output_clearance(".env", "KEY=val", Clearance.PUBLIC)
        assert ".env" in result
