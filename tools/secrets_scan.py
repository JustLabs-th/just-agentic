"""scan_secrets — detect hardcoded credentials and secrets in source files."""

import os
import re
from pathlib import Path

from langchain_core.tools import tool

from tools._safety import check_path, log_tool_call

# (label, compiled pattern)
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key",          re.compile(r"AKIA[0-9A-Z]{16}")),
    ("OpenAI Key",              re.compile(r"sk-[A-Za-z0-9]{48}")),
    ("Stripe Key",              re.compile(r"(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{24,}")),
    ("GitHub Token",            re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("Private Key Header",      re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Generic API Key",         re.compile(r"(?i)(api[_\-]?key|apikey)\s*[:=]\s*[\"']?([A-Za-z0-9\-_]{20,})")),
    ("Bearer Token",            re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{20,}=*")),
    ("Password in code",        re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*[\"']([^\"']{6,})[\"']")),
    ("DB URL with credentials", re.compile(r"(?i)(postgres|mysql|mongodb)://[^:]+:[^@]+@")),
    ("AWS Secret Key",          re.compile(r"(?i)aws.{0,20}secret.{0,5}[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+]{40}")),
]

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", "dist", "build"}
_SKIP_EXTS = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
              ".woff", ".ttf", ".pdf", ".bin", ".exe", ".zip", ".tar", ".gz"}

_MAX_FINDINGS = 100


@tool
def scan_secrets(path: str = ".") -> str:
    """Scan source files for hardcoded secrets, API keys, and credentials.

    Detects: API keys, tokens, passwords, private keys, database URLs with credentials.
    Skips: .git, node_modules, binaries, compiled files.

    Args:
        path: File or directory to scan. Defaults to current directory.
    """
    blocked = check_path(path)
    if blocked:
        log_tool_call("scan_secrets", {"path": path}, blocked)
        return blocked

    root = Path(path).resolve()
    findings: list[str] = []

    try:
        file_iter = [root] if root.is_file() else _walk_text_files(root)

        for fpath in file_iter:
            if len(findings) >= _MAX_FINDINGS:
                findings.append(f"... (scan stopped at {_MAX_FINDINGS} findings)")
                break
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                for line_no, line in enumerate(text.splitlines(), start=1):
                    for label, pattern in _PATTERNS:
                        if pattern.search(line):
                            snippet = line.strip()[:120]
                            findings.append(f"{fpath}:{line_no}  [{label}]\n  {snippet}")
                            break  # one finding per line max
            except Exception:
                continue

        if not findings:
            out = "No secrets detected."
        else:
            out = f"Found {len(findings)} potential secret(s):\n\n" + "\n\n".join(findings)

    except Exception as e:
        out = f"ERROR: {e}"

    log_tool_call("scan_secrets", {"path": path, "findings": len(findings)}, out)
    return out


def _walk_text_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in _SKIP_EXTS:
                yield fpath
