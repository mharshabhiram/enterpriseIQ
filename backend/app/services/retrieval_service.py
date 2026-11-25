import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider
from app.config import get_settings
from app.models import User
from app.repositories.documents import DocumentRepository
from app.schemas.search import SearchFilters


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID | None
    document_id: uuid.UUID | None
    document_name: str
    file_type: str
    department: str | None
    uploaded_by: uuid.UUID | None
    uploader_name: str | None
    upload_timestamp: datetime | None
    tags: list[str]
    page: int | None
    section: str | None
    text: str
    similarity: float


class RetrievalService:
    """Query embedding → permission-filtered pgvector search → ranked chunks."""

    def __init__(self, db: Session, embedder: EmbeddingProvider) -> None:
        self.db = db
        self.embedder = embedder
        self.repo = DocumentRepository(db)
        self.settings = get_settings()

    def retrieve(
        self,
        user: User,
        query: str,
        *,
        top_k: int | None = None,
        threshold: float | None = None,
        filters: SearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        vector = self.embedder.embed_query(query.strip())
        rows = self.repo.similarity_search(
            user,
            vector,
            self.embedder.model,
            top_k or self.settings.top_k,
            self.settings.similarity_threshold if threshold is None else threshold,
            filters,
        )
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=doc.id,
                document_name=doc.title,
                file_type=doc.file_type,
                department=doc.department,
                uploaded_by=doc.uploaded_by,
                uploader_name=doc.uploader.name if doc.uploader else None,
                upload_timestamp=doc.created_at,
                tags=doc.tags,
                page=chunk.page_number,
                section=chunk.section,
                text=chunk.chunk_text,
                similarity=round(sim, 4),
            )
            for chunk, doc, sim in rows
        ]


def select_context(chunks: list[RetrievedChunk], max_chars: int) -> list[RetrievedChunk]:
    """Keep the most relevant chunks that fit the context budget."""
    picked: list[RetrievedChunk] = []
    used = 0
    for chunk in sorted(chunks, key=lambda c: c.similarity, reverse=True):
        if picked and used + len(chunk.text) > max_chars:
            break
        picked.append(chunk)
        used += len(chunk.text)
    return picked
