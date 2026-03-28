"""
Audit Logger — DB-backed, append-only.

Interface unchanged: logger.log(...) → AuditRecord dataclass.
All records written to the audit_records table via SQLAlchemy.
Failures are silently swallowed so they never block a response.
"""

import hashlib
import sys
import time
from dataclasses import dataclass

from db.session import get_db
from db import models as m


@dataclass
class AuditRecord:
    timestamp: str
    user_id: str
    role: str
    department: str
    clearance_level: int
    query: str
    response_hash: str
    tools_used: list[str]
    data_classifications_accessed: list[int]
    stripped_classifications: list[int]
    iteration_count: int
    status: str
    error: str = ""


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]


class AuditLogger:
    def log(
        self,
        *,
        user_id: str,
        role: str,
        department: str,
        clearance_level: int,
        query: str,
        response: str,
        tools_used: list[str],
        data_classifications_accessed: list[int],
        stripped_classifications: list[int],
        iteration_count: int,
        status: str = "ok",
        error: str = "",
    ) -> AuditRecord:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        response_hash = _sha256(response)

        record = AuditRecord(
            timestamp=ts,
            user_id=user_id,
            role=role,
            department=department,
            clearance_level=clearance_level,
            query=query,
            response_hash=response_hash,
            tools_used=tools_used,
            data_classifications_accessed=data_classifications_accessed,
            stripped_classifications=stripped_classifications,
            iteration_count=iteration_count,
            status=status,
            error=error,
        )

        try:
            with get_db() as db:
                db.add(m.AuditRecord(
                    user_id=user_id,
                    role=role,
                    department=department,
                    clearance_level=clearance_level,
                    query=query,
                    response_hash=response_hash,
                    tools_used=tools_used,
                    data_classifications_accessed=data_classifications_accessed,
                    stripped_classifications=stripped_classifications,
                    iteration_count=iteration_count,
                    status=status,
                    error=error,
                ))
        except Exception as exc:
            # Never block the response, but make the failure visible
            print(f"[AUDIT ERROR] Failed to write audit record: {exc}", file=sys.stderr)

        return record


# Module-level singleton
logger = AuditLogger()
