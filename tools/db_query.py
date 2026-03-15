"""query_db — read-only SQL query tool for the application database."""

import os
import re

from langchain_core.tools import tool

from tools._safety import log_tool_call
from tools._permission import permission_required

_MAX_ROWS = 200

# Block any statement that modifies data or schema
_WRITE_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE,
)


@tool
@permission_required("query_db")
def query_db(sql: str) -> str:
    """Execute a read-only SQL SELECT query on the application database.

    Only SELECT statements are allowed. Results are capped at 200 rows.
    Use for: inspecting audit_records, tool_call_logs, users, roles, departments.

    Args:
        sql: A SQL SELECT statement.
    """
    if _WRITE_PATTERN.search(sql):
        out = "BLOCKED: Only SELECT statements are allowed in query_db."
        log_tool_call("query_db", {"sql": sql[:200]}, out)
        return out

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return "ERROR: DATABASE_URL is not configured."

    # Normalize to plain postgresql:// for psycopg2
    url = db_url
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql://", 1)
            break

    try:
        import psycopg2
        import psycopg2.extras

        with psycopg2.connect(url) as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchmany(_MAX_ROWS)

        if not rows:
            out = "(no rows returned)"
            log_tool_call("query_db", {"sql": sql[:200]}, out)
            return out

        cols = list(rows[0].keys())
        header = " | ".join(cols)
        sep    = " | ".join(["---"] * len(cols))
        body   = [" | ".join(str(r.get(c, "")) for c in cols) for r in rows]
        out = "\n".join([header, sep] + body)
        if len(rows) == _MAX_ROWS:
            out += f"\n\n_(results capped at {_MAX_ROWS} rows)_"

    except ImportError:
        out = "ERROR: psycopg2-binary not installed. Run: pip install psycopg2-binary"
    except Exception as e:
        out = f"ERROR: {e}"

    log_tool_call("query_db", {"sql": sql[:200]}, out)
    return out
