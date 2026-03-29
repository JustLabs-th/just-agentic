"""
Option A: Subprocess execution with OS-level resource limits.

Every dangerous command runs in a forked child process with:
  - RLIMIT_CPU   : max CPU seconds (prevents runaway loops)
  - RLIMIT_AS    : max virtual memory (prevents memory bombs)
  - RLIMIT_FSIZE : max file size written (prevents disk exhaustion)
  - RLIMIT_NPROC : max child processes (prevents fork bombs)
  - RLIMIT_NOFILE: max open file descriptors

These limits are applied via preexec_fn so they only affect the child,
never the tool-service process itself.
"""

import os
import resource
import subprocess
import tempfile


# ── Resource limit defaults (overridable via env vars) ────────────────────────

_CPU_SOFT   = int(os.getenv("SANDBOX_CPU_SOFT",  "30"))    # 30 s CPU time
_CPU_HARD   = int(os.getenv("SANDBOX_CPU_HARD",  "60"))    # hard kill at 60 s
_MEM_MB     = int(os.getenv("SANDBOX_MEM_MB",    "512"))   # 512 MB virtual mem
_FSIZE_MB   = int(os.getenv("SANDBOX_FSIZE_MB",  "50"))    # 50 MB max file write
_NPROC      = int(os.getenv("SANDBOX_NPROC",     "64"))    # 64 child processes
_NOFILE     = int(os.getenv("SANDBOX_NOFILE",    "128"))   # 128 open FDs


def _apply_limits() -> None:
    """
    Preexec_fn — called in the forked child process before exec().
    Sets resource limits for that child only.
    """
    mem = _MEM_MB * 1024 * 1024
    fsize = _FSIZE_MB * 1024 * 1024

    try:
        resource.setrlimit(resource.RLIMIT_CPU,   (_CPU_SOFT,  _CPU_HARD))
        resource.setrlimit(resource.RLIMIT_AS,    (mem,        mem))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize,      fsize))
        resource.setrlimit(resource.RLIMIT_NPROC, (_NPROC,     _NPROC))
        resource.setrlimit(resource.RLIMIT_NOFILE,(_NOFILE,    _NOFILE))
    except (ValueError, resource.error):
        pass  # some limits may not be supported in certain environments


# ── Public runners ────────────────────────────────────────────────────────────

def run_command(command: str, workspace: str | None, timeout: int) -> str:
    """
    Run a shell command with resource limits applied.
    Returns combined stdout/stderr + exit code string.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workspace,
            preexec_fn=_apply_limits,
        )
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}"
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        output = output or "(no output)"
        output += f"\nEXIT CODE: {result.returncode}"
    except subprocess.TimeoutExpired:
        output = f"ERROR: Command timed out after {timeout} seconds"
    except Exception as exc:
        output = f"ERROR: {exc}"
    return output


def run_python(code: str, timeout: int) -> str:
    """
    Write code to a temp file and run it with resource limits applied.
    Returns combined stdout/stderr + exit code string.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
            dir="/tmp",
        ) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_apply_limits,
        )
        output = ""
        if result.stdout:
            output += f"OUTPUT:\n{result.stdout}"
        if result.stderr:
            output += f"\nERROR:\n{result.stderr}"
        output = output or "(no output)"
        output += f"\nEXIT CODE: {result.returncode}"
    except subprocess.TimeoutExpired:
        output = f"ERROR: Code execution timed out after {timeout} seconds"
    except Exception as exc:
        output = f"ERROR: {exc}"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return output
