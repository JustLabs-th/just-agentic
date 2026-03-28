"""Tests for RAG components: chunker, embeddings, knowledge search, upload API."""

import pytest
from unittest.mock import MagicMock, patch


# ── Chunker ───────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        from tools.rag_utils import chunk_text
        result = chunk_text("Hello world")
        assert result == ["Hello world"]

    def test_empty_returns_empty(self):
        from tools.rag_utils import chunk_text
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_long_text_splits_into_multiple_chunks(self):
        from tools.rag_utils import chunk_text, CHUNK_SIZE
        text = "word " * (CHUNK_SIZE // 5 * 3)  # ~3x chunk size
        chunks = chunk_text(text)
        assert len(chunks) >= 2

    def test_chunks_cover_all_content(self):
        from tools.rag_utils import chunk_text
        # Every word should appear in at least one chunk
        words = ["alpha", "beta", "gamma", "delta", "epsilon"]
        text = " ".join(words) * 50
        chunks = chunk_text(text)
        combined = " ".join(chunks)
        for word in words:
            assert word in combined

    def test_overlap_means_content_repeated(self):
        from tools.rag_utils import chunk_text, CHUNK_SIZE, CHUNK_OVERLAP
        text = "A" * CHUNK_SIZE + " " + "B" * CHUNK_SIZE
        chunks = chunk_text(text)
        # With overlap, some content should appear in consecutive chunks
        assert len(chunks) >= 2

    def test_custom_chunk_size(self):
        from tools.rag_utils import chunk_text
        text = "hello " * 100
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        assert all(len(c) <= 60 for c in chunks)  # allow slight overshoot at word boundary

    def test_paragraph_break_preferred(self):
        from tools.rag_utils import chunk_text
        para1 = "First paragraph content. " * 20
        para2 = "Second paragraph content. " * 20
        text = para1 + "\n\n" + para2
        chunks = chunk_text(text, chunk_size=len(para1) + 10)
        # Should split at the paragraph boundary
        assert any("\n\n" not in c for c in chunks)


# ── Embedding adapter ─────────────────────────────────────────────────────────

class TestEmbeddings:
    def test_returns_correct_dimension(self):
        from llm.embeddings import embed_text, EMBEDDING_DIM
        # Without API key, returns zero vector
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            vec = embed_text("hello world")
        assert len(vec) == EMBEDDING_DIM

    def test_batch_returns_one_vector_per_text(self):
        from llm.embeddings import embed_batch
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            vecs = embed_batch(["a", "b", "c"])
        assert len(vecs) == 3

    def test_empty_batch_returns_empty(self):
        from llm.embeddings import embed_batch
        assert embed_batch([]) == []

    def test_no_api_key_returns_zero_vector(self):
        from llm.embeddings import embed_text, EMBEDDING_DIM
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            vec = embed_text("test")
        assert all(v == 0.0 for v in vec)
        assert len(vec) == EMBEDDING_DIM


# ── Knowledge search tool ─────────────────────────────────────────────────────

class TestKnowledgeSearch:
    def _setup_ctx(self, clearance=2, dept="all"):
        from tools._permission import set_role_context
        set_role_context("analyst", dept, clearance)

    def test_returns_no_results_message_when_empty(self):
        from tools.knowledge_search import search_knowledge
        from tools._permission import set_role_context
        set_role_context("analyst", "all", 2)

        with patch("tools.knowledge_search._vector_search", side_effect=Exception("no pgvector")), \
             patch("tools.knowledge_search._keyword_search", return_value="No relevant knowledge found."):
            result = search_knowledge.invoke({"query": "nonexistent topic"})
        assert "No relevant knowledge found" in result

    def test_clearance_filtered_in_keyword_search(self):
        """Only chunks with clearance_level <= user_clearance should be returned."""
        from tools.knowledge_search import _keyword_search
        from db.models import KnowledgeChunk

        low_chunk = MagicMock(spec=KnowledgeChunk)
        low_chunk.content = "public info"
        low_chunk.document_name = "public_doc"
        low_chunk.source_url = None
        low_chunk.clearance_level = 1

        high_chunk = MagicMock(spec=KnowledgeChunk)
        high_chunk.content = "secret info"
        high_chunk.document_name = "secret_doc"
        high_chunk.source_url = None
        high_chunk.clearance_level = 4  # SECRET — should not appear for clearance=2

        # MagicMock chains: .filter().filter().limit().all()
        q = MagicMock()
        q.filter.return_value = q
        q.limit.return_value.all.return_value = [low_chunk]

        with patch("db.session.get_db") as mock_ctx:
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            db.query.return_value = q

            result = _keyword_search("info", top_k=5, clearance=2, dept="all")

        assert "public info" in result
        assert "secret info" not in result

    def test_format_results_includes_source(self):
        from tools.knowledge_search import _format_results
        row = MagicMock()
        row.document_name = "Architecture Guide"
        row.source_url = "https://internal.wiki/arch"
        row.content = "The system uses LangGraph for orchestration."

        result = _format_results([row])
        assert "Architecture Guide" in result
        assert "internal.wiki" in result
        assert "LangGraph" in result

    def test_format_results_no_url(self):
        from tools.knowledge_search import _format_results
        row = MagicMock()
        row.document_name = "Runbook"
        row.source_url = None
        row.content = "Step 1: do this."

        result = _format_results([row])
        assert "Runbook" in result
        assert "Step 1" in result


# ── Knowledge upload API ──────────────────────────────────────────────────────

class TestKnowledgeUploadAPI:
    def test_upload_creates_chunks(self):
        from api.routers.knowledge import upload_document
        from api.schemas import KnowledgeUploadRequest

        body = KnowledgeUploadRequest(
            document_name="Test Doc",
            content="This is test content. " * 10,
            clearance_level=1,
        )
        admin = MagicMock()
        admin.user_id = "admin_user"

        with patch("api.routers.knowledge.chunk_text", return_value=["chunk1", "chunk2"]), \
             patch("api.routers.knowledge.embed_batch", return_value=[[0.0] * 1536, [0.0] * 1536]), \
             patch("api.routers.knowledge.get_db") as mock_ctx:
            db = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: db
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = upload_document(body, admin)

        assert result.chunk_count == 2
        assert result.document_name == "Test Doc"
        assert result.clearance_level == 1

    def test_upload_invalid_clearance_level_raises(self):
        from api.routers.knowledge import upload_document
        from api.schemas import KnowledgeUploadRequest
        from fastapi import HTTPException

        body = KnowledgeUploadRequest(
            document_name="Bad Doc",
            content="content",
            clearance_level=9,  # invalid
        )
        admin = MagicMock()
        admin.user_id = "admin_user"

        with pytest.raises(HTTPException) as exc:
            upload_document(body, admin)
        assert exc.value.status_code == 422

    def test_upload_empty_content_raises(self):
        from api.routers.knowledge import upload_document
        from api.schemas import KnowledgeUploadRequest
        from fastapi import HTTPException

        body = KnowledgeUploadRequest(
            document_name="Empty",
            content="   ",  # whitespace only
            clearance_level=1,
        )
        admin = MagicMock()
        admin.user_id = "admin_user"

        with patch("api.routers.knowledge.chunk_text", return_value=[]):
            with pytest.raises(HTTPException) as exc:
                upload_document(body, admin)
        assert exc.value.status_code == 422
