import os
import subprocess
from langchain_core.tools import tool
from tools._safety import check_path, resolve_path, log_tool_call
from tools._permission import permission_required, _clearance_ctx
from security.output_classifier import check_output_clearance


@tool
def read_file(path: str) -> str:
    """Read the contents of a UTF-8 text file from the workspace."""
    blocked = check_path(path)
    if blocked:
        log_tool_call("read_file", {"path": path}, blocked)
        return blocked
    try:
        real = resolve_path(path)
        with open(real, "r", encoding="utf-8") as f:
            content = f.read()
        redacted = check_output_clearance(str(real), content, _clearance_ctx.get())
        if redacted:
            log_tool_call("read_file", {"path": path}, redacted)
            return redacted
        log_tool_call("read_file", {"path": path}, content)
        return content
    except FileNotFoundError:
        out = f"ERROR: File not found: {path}"
        log_tool_call("read_file", {"path": path}, out)
        return out
    except Exception as e:
        out = f"ERROR: {e}"
        log_tool_call("read_file", {"path": path}, out)
        return out


@tool
@permission_required("write_file")
def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed. Overwrites existing files."""
    blocked = check_path(path)
    if blocked:
        log_tool_call("write_file", {"path": path}, blocked)
        return blocked
    try:
        real = resolve_path(path)
        real.parent.mkdir(parents=True, exist_ok=True)
        with open(real, "w", encoding="utf-8") as f:
            f.write(content)
        out = f"OK: Written {len(content)} chars to {real}"
        log_tool_call("write_file", {"path": path, "bytes": len(content)}, out)
        return out
    except Exception as e:
        out = f"ERROR: {e}"
        log_tool_call("write_file", {"path": path}, out)
        return out


@tool
def list_files(path: str = ".") -> str:
    """List files and directories at the given path. Defaults to current directory."""
    blocked = check_path(path)
    if blocked:
        log_tool_call("list_files", {"path": path}, blocked)
        return blocked
    try:
        real = resolve_path(path)
        entries = os.listdir(real)
        lines = []
        for entry in sorted(entries):
            full = real / entry
            tag = "/" if full.is_dir() else ""
            lines.append(f"{entry}{tag}")
        out = "\n".join(lines) if lines else "(empty directory)"
        log_tool_call("list_files", {"path": path}, out)
        return out
    except FileNotFoundError:
        out = f"ERROR: Directory not found: {path}"
        log_tool_call("list_files", {"path": path}, out)
        return out
    except Exception as e:
        out = f"ERROR: {e}"
        log_tool_call("list_files", {"path": path}, out)
        return out


@tool
@permission_required("write_file")
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Edit a file by replacing old_string with new_string.

    Rules:
    - old_string must match exactly once in the file (fails if 0 or 2+ matches)
    - Preserves all content outside the matched region
    - Use this instead of write_file when changing part of an existing file
    """
    blocked = check_path(path)
    if blocked:
        log_tool_call("edit_file", {"path": path}, blocked)
        return blocked
    try:
        real = resolve_path(path)
        with open(real, "r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            out = f"ERROR: old_string not found in {real}"
            log_tool_call("edit_file", {"path": path}, out)
            return out
        if count > 1:
            out = f"ERROR: old_string matches {count} times in {real} — make it unique by including more context"
            log_tool_call("edit_file", {"path": path}, out)
            return out
        updated = content.replace(old_string, new_string, 1)
        with open(real, "w", encoding="utf-8") as f:
            f.write(updated)
        out = f"OK: Edited {real} ({len(old_string)} chars → {len(new_string)} chars)"
        log_tool_call("edit_file", {"path": path}, out)
        return out
    except FileNotFoundError:
        out = f"ERROR: File not found: {path}"
        log_tool_call("edit_file", {"path": path}, out)
        return out
    except Exception as e:
        out = f"ERROR: {e}"
        log_tool_call("edit_file", {"path": path}, out)
        return out


@tool
def search_code(keyword: str, path: str = ".") -> str:
    """Search for a keyword in source code files under the given path.

    Uses grep to find occurrences. Returns file:line matches.
    """
    blocked = check_path(path)
    if blocked:
        log_tool_call("search_code", {"keyword": keyword, "path": path}, blocked)
        return blocked
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.go", "--include=*.ts",
             "--include=*.js", "--include=*.java", "--include=*.sh",
             keyword, path],
            capture_output=True, text=True, timeout=15,
        )
        out = result.stdout.strip() or "(no matches found)"
        if result.stderr:
            out += f"\nSTDERR: {result.stderr.strip()}"
        log_tool_call("search_code", {"keyword": keyword, "path": path}, out)
        return out
    except subprocess.TimeoutExpired:
        return "ERROR: search_code timed out after 15 seconds"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def read_log(path: str, tail: int = 100) -> str:
    """Read the last N lines of a log file. Default: last 100 lines."""
    blocked = check_path(path)
    if blocked:
        log_tool_call("read_log", {"path": path}, blocked)
        return blocked
    try:
        real = resolve_path(path)
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        out = "".join(lines[-tail:])
        redacted = check_output_clearance(str(real), out, _clearance_ctx.get())
        if redacted:
            log_tool_call("read_log", {"path": path}, redacted)
            return redacted
        log_tool_call("read_log", {"path": path, "tail": tail}, out)
        return out or "(empty log)"
    except FileNotFoundError:
        out = f"ERROR: Log file not found: {path}"
        log_tool_call("read_log", {"path": path}, out)
        return out
    except Exception as e:
        return f"ERROR: {e}"
