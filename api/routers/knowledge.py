"""
Knowledge base router — admin CRUD for RAG documents.

Endpoints:
  POST   /api/admin/knowledge          — upload + chunk + embed document
  GET    /api/admin/knowledge          — list all documents (one row per document_id)
  DELETE /api/admin/knowledge/{doc_id} — soft-delete all chunks of a document
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_admin
from api.schemas import KnowledgeUploadRequest, KnowledgeDocumentResponse
from db.models import KnowledgeChunk
from db.session import get_db
from llm.embeddings import embed_batch
from security.jwt_auth import UserContext
from tools.rag_utils import chunk_text

router = APIRouter(prefix="/api/admin/knowledge", tags=["knowledge"])


@router.post("", response_model=KnowledgeDocumentResponse, status_code=201)
def upload_document(
    body: KnowledgeUploadRequest,
    admin: UserContext = Depends(require_admin),
):
    """Chunk, embed, and store a document in the knowledge base."""
    if body.clearance_level not in (1, 2, 3, 4):
        raise HTTPException(status_code=422, detail="clearance_level must be 1–4")

    chunks = chunk_text(body.content)
    if not chunks:
        raise HTTPException(status_code=422, detail="Document content is empty after chunking")

    # Embed all chunks in one batch call
    embeddings = embed_batch(chunks)

    doc_id = str(uuid.uuid4())

    with get_db() as db:
        for idx, (text, vec) in enumerate(zip(chunks, embeddings)):
            chunk = KnowledgeChunk(
                document_id=doc_id,
                document_name=body.document_name,
                chunk_index=idx,
                content=text,
                clearance_level=body.clearance_level,
                department=body.department,
                source_url=body.source_url,
                created_by=admin.user_id,
                is_active=True,
            )
            # Set embedding only if pgvector is available
            try:
                chunk.embedding = vec
            except Exception:
                pass
            db.add(chunk)

    return KnowledgeDocumentResponse(
        document_id=doc_id,
        document_name=body.document_name,
        chunk_count=len(chunks),
        clearance_level=body.clearance_level,
        department=body.department,
        source_url=body.source_url,
        created_by=admin.user_id,
        created_at=datetime.utcnow(),
    )


@router.get("", response_model=list[KnowledgeDocumentResponse])
def list_documents(admin: UserContext = Depends(require_admin)):
    """List all active documents (grouped by document_id)."""
    with get_db() as db:
        rows = db.query(KnowledgeChunk).filter_by(is_active=True).all()

    # Group by document_id
    docs: dict[str, dict] = {}
    for row in rows:
        if row.document_id not in docs:
            docs[row.document_id] = {
                "document_id": row.document_id,
                "document_name": row.document_name,
                "chunk_count": 0,
                "clearance_level": row.clearance_level,
                "department": row.department,
                "source_url": row.source_url,
                "created_by": row.created_by,
                "created_at": row.created_at,
            }
        docs[row.document_id]["chunk_count"] += 1

    return [KnowledgeDocumentResponse(**d) for d in docs.values()]


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, admin: UserContext = Depends(require_admin)):
    """Soft-delete all chunks of a document."""
    with get_db() as db:
        chunks = db.query(KnowledgeChunk).filter_by(document_id=document_id, is_active=True).all()
        if not chunks:
            raise HTTPException(status_code=404, detail="Document not found")
        for chunk in chunks:
            chunk.is_active = False
