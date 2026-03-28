"""
Tool Output Classifier

Classifies file paths and tool output content to prevent
low-clearance agents from reading data above their clearance.

Used by read_file and read_log tools.
"""

import re

# Clearance level constants (mirrors db/seed.py level_order values)
class Clearance:
    PUBLIC       = 1
    INTERNAL     = 2
    CONFIDENTIAL = 3
    SECRET       = 4

    _LABELS = {1: "PUBLIC", 2: "INTERNAL", 3: "CONFIDENTIAL", 4: "SECRET"}

    @classmethod
    def label(cls, level: int) -> str:
        return cls._LABELS.get(level, f"LEVEL({level})")

# ── Path-based classification ──────────────────────────────────────────────
# Paths matching these patterns are treated as the given classification level.
# More specific patterns should come first.

_PATH_RULES: list[tuple[re.Pattern, int]] = [
    (re.compile(r"secrets?/|\.pem$|\.key$|\.p12$|\.pfx$", re.I), Clearance.SECRET),
    (re.compile(r"\.env(\..+)?$|credentials?|api[_-]?keys?", re.I), Clearance.CONFIDENTIAL),
    (re.compile(r"config/|settings\.py$|\.ya?ml$", re.I),          Clearance.INTERNAL),
]

# ── Content-based classification ───────────────────────────────────────────
_CONTENT_RULES: list[tuple[re.Pattern, int]] = [
    # Private keys / certs
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY", re.I), Clearance.SECRET),
    # Secrets / tokens in content
    (re.compile(r"(password|passwd|secret|api_key|apikey)\s*=\s*['\"]?\S{8,}", re.I), Clearance.CONFIDENTIAL),
    (re.compile(r"token\s*=\s*['\"]?\S{8,}", re.I), Clearance.CONFIDENTIAL),
    (re.compile(r"token=[A-Za-z]+\s+[A-Za-z0-9._-]{8,}", re.I), Clearance.CONFIDENTIAL),
]


def classify_path(path: str) -> int:
    """Return the classification level for a file path. Defaults to PUBLIC."""
    for pattern, level in _PATH_RULES:
        if pattern.search(path):
            return level
    return Clearance.PUBLIC


def classify_content(content: str) -> int:
    """Return the highest classification level found in content."""
    highest = Clearance.PUBLIC
    for pattern, level in _CONTENT_RULES:
        if pattern.search(content):
            highest = max(highest, level)
    return highest


def check_output_clearance(path: str, content: str, user_clearance: int = 0) -> str | None:
    """
    Returns a redaction message if path or content exceeds user clearance.
    Returns None if content is safe to show.
    """
    path_level    = classify_path(path)
    content_level = classify_content(content)
    effective     = max(path_level, content_level)

    if effective > user_clearance:
        label = Clearance.label(effective)
        return (
            f"[REDACTED] File '{path}' is classified {label} "
            f"(clearance required: {effective}, your clearance: {user_clearance}). "
            f"Access denied."
        )
    return None
