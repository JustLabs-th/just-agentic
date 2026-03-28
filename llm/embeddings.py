"""
Embedding adapter — wraps OpenAI text-embedding-3-small.

Usage:
    from llm.embeddings import embed_text, embed_batch

Returns a list of floats (1536-dim vector).
Falls back gracefully when OPENAI_API_KEY is not set (returns zero vector).
"""

import os
from functools import lru_cache

EMBEDDING_DIM = 1536
_MODEL = "text-embedding-3-small"


def embed_text(text: str) -> list[float]:
    """Embed a single string. Returns 1536-dim vector."""
    return embed_batch([text])[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings in one API call."""
    if not texts:
        return []

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        # Fallback: return zero vectors (useful for SQLite test env)
        return [[0.0] * EMBEDDING_DIM for _ in texts]

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        # Truncate to avoid token limit
        clean = [t.replace("\n", " ")[:8000] for t in texts]
        resp = client.embeddings.create(model=_MODEL, input=clean)
        return [item.embedding for item in resp.data]
    except Exception:
        return [[0.0] * EMBEDDING_DIM for _ in texts]
