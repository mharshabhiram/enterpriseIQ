"""Document chunk repository."""
import uuid
from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import Row, delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.types import ChunkData
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.enums import ProcessingStatus
from app.models.user import User
from app.repositories.document_repository import visibility_clause


async def bulk_create(
    session: AsyncSession, *, document_id: uuid.UUID, chunks: List[ChunkData]
) -> List[DocumentChunk]:
    rows = [
        DocumentChunk(
            document_id=document_id,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
        )
        for chunk in chunks
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def list_for_document_ordered(session: AsyncSession, document_id: uuid.UUID) -> List[DocumentChunk]:
    """All chunks for a document, in reading order - used by summarization and comparison."""
    result = await session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


async def delete_for_document(session: AsyncSession, document_id: uuid.UUID) -> None:
    """Used when reprocessing a document (not exercised until a future phase)."""
    await session.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    await session.flush()


async def search_similar(
    session: AsyncSession,
    user: User,
    query_vector: Sequence[float],
    *,
    top_k: int,
    similarity_threshold: float,
    file_type: Optional[str] = None,
    uploaded_by: Optional[uuid.UUID] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
) -> List[Row]:
    """
    RBAC-filtered pgvector cosine similarity search.

    Same principle as document_repository.visibility_clause: permission
    filtering happens *inside* the SQL query (an unauthorized chunk is never
    fetched, let alone ranked or returned) - not applied as a filter on
    results after the fact. Only chunks belonging to fully COMPLETED
    documents with a non-null embedding are eligible, and the similarity
    threshold is applied in the WHERE clause too, so the database does the
    filtering work rather than the application discarding rows in Python.

    Returns rows of (DocumentChunk, Document, relevance_score), ordered by
    descending relevance, limited to top_k.
    """
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    relevance_score = (1 - distance).label("relevance_score")

    stmt = (
        select(DocumentChunk, Document, relevance_score)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(
            visibility_clause(user),
            Document.processing_status == ProcessingStatus.COMPLETED,
            DocumentChunk.embedding.is_not(None),
            relevance_score >= similarity_threshold,
        )
    )

    if file_type is not None:
        stmt = stmt.where(Document.file_type == file_type)
    if uploaded_by is not None:
        stmt = stmt.where(Document.uploaded_by == uploaded_by)
    if created_after is not None:
        stmt = stmt.where(Document.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(Document.created_at <= created_before)

    stmt = stmt.order_by(distance.asc()).limit(top_k)

    result = await session.execute(stmt)
    return list(result.all())
