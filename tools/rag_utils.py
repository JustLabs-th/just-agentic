"""
Text chunking utility for RAG ingestion.

Splits a document into overlapping chunks suitable for embedding.
Chunk size and overlap are in characters (not tokens) for simplicity.
"""

CHUNK_SIZE = 1200    # ~300 tokens at 4 chars/token
CHUNK_OVERLAP = 200


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into overlapping chunks.

    Tries to break at paragraph boundaries first, then sentence ends,
    then hard-cuts if necessary.
    """
    text = text.strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        if end < len(text):
            # Prefer paragraph break
            para_break = text.rfind("\n\n", start, end)
            if para_break > start + overlap:
                end = para_break + 2
            else:
                # Prefer sentence end
                for sep in (". ", "! ", "? ", "\n"):
                    pos = text.rfind(sep, start + overlap, end)
                    if pos > start + overlap:
                        end = pos + len(sep)
                        break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        start = end - overlap

    return chunks
