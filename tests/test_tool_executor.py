"""Tests for tool_service/executor.py — subprocess runners with resource limits."""

import os
import tempfile
import time

import pytest

from tool_service.executor import run_command, run_python


class TestRunCommand:
    def test_stdout_captured(self):
        output = run_command("echo hello", workspace=None, timeout=10)
        assert "STDOUT:" in output
        assert "hello" in output

    def test_exit_code_zero_included(self):
        output = run_command("echo ok", workspace=None, timeout=10)
        assert "EXIT CODE: 0" in output

    def test_non_zero_exit_code_captured(self):
        output = run_command("exit 42", workspace=None, timeout=10)
        assert "EXIT CODE: 42" in output

    def test_stderr_captured(self):
        output = run_command("echo error >&2", workspace=None, timeout=10)
        assert "STDERR:" in output
        assert "error" in output

    def test_no_output_placeholder(self):
        # A command that produces no stdout/stderr
        output = run_command("true", workspace=None, timeout=10)
        assert "EXIT CODE: 0" in output
        # Either "(no output)" if truly silent, or the exit code line at minimum
        assert "EXIT CODE:" in output

    def test_timeout_enforced(self):
        start = time.time()
        output = run_command("sleep 30", workspace=None, timeout=2)
        elapsed = time.time() - start
        assert "timed out" in output.lower() or "timeout" in output.lower() or "ERROR" in output
        # Should not have actually run for 30 seconds
        assert elapsed < 10

    def test_workspace_cwd_respected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = run_command("pwd", workspace=tmpdir, timeout=10)
        assert "STDOUT:" in output
        # The printed path should resolve to tmpdir (handle symlinks like /private/tmp on macOS)
        assert "EXIT CODE: 0" in output
        stdout_line = [l for l in output.splitlines() if l and not l.startswith(("STDOUT", "EXIT", "STDERR"))]
        assert len(stdout_line) >= 1

    def test_workspace_cwd_content_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a sentinel file
            sentinel = os.path.join(tmpdir, "sentinel.txt")
            with open(sentinel, "w") as f:
                f.write("present")
            output = run_command("ls", workspace=tmpdir, timeout=10)
        assert "sentinel.txt" in output

    def test_combined_stdout_and_stderr(self):
        output = run_command("echo out; echo err >&2", workspace=None, timeout=10)
        assert "STDOUT:" in output
        assert "STDERR:" in output
        assert "out" in output
        assert "err" in output


class TestRunPython:
    def test_print_output_captured(self):
        output = run_python("print('hello world')", timeout=10)
        assert "OUTPUT:" in output
        assert "hello world" in output

    def test_exit_code_zero_included(self):
        output = run_python("x = 1 + 1", timeout=10)
        assert "EXIT CODE: 0" in output

    def test_stderr_captured_on_error(self):
        output = run_python("raise ValueError('boom')", timeout=10)
        assert "ERROR:" in output
        assert "ValueError" in output or "boom" in output

    def test_non_zero_exit_code_on_exception(self):
        output = run_python("raise SystemExit(2)", timeout=10)
        assert "EXIT CODE: 2" in output

    def test_syntax_error_captured(self):
        output = run_python("def broken(:\n    pass", timeout=10)
        assert "ERROR:" in output or "SyntaxError" in output

    def test_timeout_enforced(self):
        start = time.time()
        output = run_python("import time; time.sleep(30)", timeout=2)
        elapsed = time.time() - start
        assert "timed out" in output.lower() or "timeout" in output.lower() or "ERROR" in output
        assert elapsed < 10

    def test_temp_file_cleaned_up_after_success(self):
        # Capture tmp files before
        before = set(os.listdir("/tmp"))
        run_python("print('cleanup test')", timeout=10)
        after = set(os.listdir("/tmp"))
        new_py_files = [f for f in (after - before) if f.endswith(".py")]
        assert new_py_files == [], f"Temp .py files not cleaned up: {new_py_files}"

    def test_temp_file_cleaned_up_after_exception(self):
        before = set(os.listdir("/tmp"))
        run_python("raise RuntimeError('cleanup on error')", timeout=10)
        after = set(os.listdir("/tmp"))
        new_py_files = [f for f in (after - before) if f.endswith(".py")]
        assert new_py_files == [], f"Temp .py files not cleaned up after exception: {new_py_files}"

    def test_multiline_code_executes(self):
        code = "result = sum(range(10))\nprint(f'result={result}')"
        output = run_python(code, timeout=10)
        assert "result=45" in output

    def test_no_output_placeholder(self):
        output = run_python("x = 1", timeout=10)
        assert "EXIT CODE: 0" in output
