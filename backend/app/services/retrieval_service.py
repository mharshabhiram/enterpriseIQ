"""
Retrieval service - project brief section 7's query-time pipeline:
question -> query embedding -> pgvector search -> permission filtering ->
ranked results. Permission filtering happens inside the SQL query itself
(see document_chunk_repository.search_similar), not as a Python-side filter
afterward - the same principle used for document visibility throughout.

This phase's deliverable is the standalone semantic search endpoint
(POST /api/search, section 10). Phase 6 reuses this same function as the
retrieval step inside the full RAG question-answering pipeline, feeding its
results to an LLM instead of (or in addition to) returning them directly.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.factory import get_embedding_provider
from app.config import settings
from app.models.user import User
from app.repositories import document_chunk_repository
from app.schemas.search import SearchResultItem


async def search(
    session: AsyncSession,
    user: User,
    query: str,
    *,
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    file_type: Optional[str] = None,
    uploaded_by=None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> List[SearchResultItem]:
    provider = embedding_provider or get_embedding_provider()
    query_vectors = await provider.embed([query])
    query_vector = query_vectors[0]

    rows = await document_chunk_repository.search_similar(
        session,
        user,
        query_vector,
        top_k=top_k if top_k is not None else settings.top_k,
        similarity_threshold=(
            similarity_threshold if similarity_threshold is not None else settings.similarity_threshold
        ),
        file_type=file_type,
        uploaded_by=uploaded_by,
        created_after=created_after,
        created_before=created_before,
    )

    return [
        SearchResultItem(
            document_id=document.id,
            document_name=document.original_filename,
            chunk_id=chunk.id,
            excerpt=chunk.chunk_text,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            relevance_score=round(float(score), 4),
        )
        for chunk, document, score in rows
    ]
