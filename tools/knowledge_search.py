"""
Tool: search_knowledge

Semantic search over the knowledge base using pgvector cosine similarity.
Results are filtered by:
  1. User clearance level (hard floor — never returns above-clearance content)
  2. User department (if chunk is department-restricted)
  3. is_active flag (soft-deleted chunks excluded)

Falls back to keyword (LIKE) search when pgvector is unavailable (SQLite/test env).
"""

from langchain_core.tools import tool

from tools._permission import permission_required, _clearance_ctx, _dept_ctx


@tool
@permission_required("search_knowledge")
def search_knowledge(query: str, top_k: int = 5) -> str:
    """Search the internal knowledge base for information relevant to the query.

    Returns the most relevant document chunks based on semantic similarity,
    filtered by your clearance level and department access.

    Args:
        query: The question or topic to search for.
        top_k: Number of results to return (default 5, max 10).
    """
    top_k = min(max(1, top_k), 10)
    user_clearance = _clearance_ctx.get()
    user_dept = _dept_ctx.get() or "all"

    try:
        return _vector_search(query, top_k, user_clearance, user_dept)
    except Exception as exc:
        # pgvector not available — fall back to keyword search
        try:
            return _keyword_search(query, top_k, user_clearance, user_dept)
        except Exception as exc2:
            return f"[knowledge_search error] {exc2}"


def _vector_search(query: str, top_k: int, clearance: int, dept: str) -> str:
    from llm.embeddings import embed_text
    from db.models import KnowledgeChunk
    from db.session import get_db

    query_vec = embed_text(query)

    with get_db() as db:
        # Build base filter
        filters = [
            KnowledgeChunk.is_active == True,           # noqa: E712
            KnowledgeChunk.clearance_level <= clearance,
        ]
        if dept != "all":
            from sqlalchemy import or_
            filters.append(
                or_(KnowledgeChunk.department == dept, KnowledgeChunk.department == None)  # noqa: E711
            )

        # pgvector cosine distance ordering
        from sqlalchemy import text as sa_text
        rows = (
            db.query(KnowledgeChunk)
            .filter(*filters)
            .order_by(
                sa_text("embedding <=> CAST(:vec AS vector)").bindparams(
                    vec=str(query_vec)
                )
            )
            .limit(top_k)
            .all()
        )

        if not rows:
            return "No relevant knowledge found."

        return _format_results(rows)


def _keyword_search(query: str, top_k: int, clearance: int, dept: str) -> str:
    """Fallback: simple LIKE search for SQLite / no-vector environments."""
    from db.models import KnowledgeChunk
    from db.session import get_db
    from sqlalchemy import or_

    keywords = query.strip().split()[:5]  # use first 5 words

    with get_db() as db:
        filters = [
            KnowledgeChunk.is_active == True,           # noqa: E712
            KnowledgeChunk.clearance_level <= clearance,
        ]
        if dept != "all":
            filters.append(
                or_(KnowledgeChunk.department == dept, KnowledgeChunk.department == None)  # noqa: E711
            )

        q = db.query(KnowledgeChunk).filter(*filters)

        # Apply keyword filters — OR across keywords
        if keywords:
            from sqlalchemy import or_
            kw_filters = [
                KnowledgeChunk.content.ilike(f"%{kw}%") for kw in keywords
            ]
            q = q.filter(or_(*kw_filters))

        rows = q.limit(top_k).all()

        if not rows:
            return "No relevant knowledge found."

        return _format_results(rows)


def _format_results(rows) -> str:
    parts = []
    for i, row in enumerate(rows, 1):
        parts.append(
            f"[{i}] Source: {row.document_name}"
            + (f" ({row.source_url})" if row.source_url else "")
            + f"\n{row.content}"
        )
    return "\n\n---\n\n".join(parts)
