"""
Embedding service.

Takes chunks already stored by the ingestion pipeline and fills in their
`embedding` column via the configured EmbeddingProvider, batching requests
so a large document doesn't send one enormous API call. Accepts an optional
explicit provider (defaulting to the configured one via the factory) purely
for testability - see app.services.ingestion_service and
tests/test_ingestion.py, which inject a MockEmbeddingProvider so the whole
pipeline can be exercised without network access or a real API key.
"""
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.factory import get_embedding_provider
from app.models.document_chunk import DocumentChunk
from app.utils.errors import EmbeddingProviderError

_BATCH_SIZE = 100


async def generate_embeddings(
    session: AsyncSession,
    chunks: List[DocumentChunk],
    *,
    provider: Optional[EmbeddingProvider] = None,
) -> None:
    if not chunks:
        return

    provider = provider or get_embedding_provider()

    for start in range(0, len(chunks), _BATCH_SIZE):
        batch = chunks[start : start + _BATCH_SIZE]
        texts = [chunk.chunk_text for chunk in batch]
        vectors = await provider.embed(texts)
        if len(vectors) != len(batch):
            raise EmbeddingProviderError(
                f"Embedding provider returned {len(vectors)} vectors for {len(batch)} inputs."
            )
        for chunk, vector in zip(batch, vectors):
            chunk.embedding = vector

    await session.flush()
