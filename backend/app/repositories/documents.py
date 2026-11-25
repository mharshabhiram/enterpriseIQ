import uuid

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, DocumentStatus, User
from app.schemas.search import SearchFilters
from app.security.permissions import accessible_documents_clause


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, document_id: uuid.UUID) -> Document | None:
        return self.db.get(Document, document_id)

    def get_accessible(self, user: User, document_id: uuid.UUID) -> Document | None:
        return self.db.scalar(select(Document).where(Document.id == document_id, accessible_documents_clause(user)))

    def list_accessible(self, user: User, status: DocumentStatus | None = None, q: str | None = None) -> list[Document]:
        stmt = select(Document).where(accessible_documents_clause(user)).order_by(Document.created_at.desc())
        if status:
            stmt = stmt.where(Document.processing_status == status)
        if q:
            stmt = stmt.where(Document.title.ilike(f"%{q}%"))
        return list(self.db.scalars(stmt).unique())

    def chunks(self, document_id: uuid.UUID, limit: int = 2000) -> list[DocumentChunk]:
        return list(
            self.db.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index).limit(limit)
            )
        )

    def replace_chunks(self, document_id: uuid.UUID, chunks: list[DocumentChunk]) -> None:
        self.db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        self.db.add_all(chunks)

    def count_by_status(self, user: User) -> dict[str, int]:
        rows = self.db.execute(
            select(Document.processing_status, func.count(Document.id))
            .where(accessible_documents_clause(user))
            .group_by(Document.processing_status)
        ).all()
        return {status.value: n for status, n in rows}

    def similarity_search(
        self,
        user: User,
        query_embedding: list[float],
        embedding_model: str,
        top_k: int,
        threshold: float,
        filters: SearchFilters | None = None,
    ) -> list[tuple[DocumentChunk, Document, float]]:
        """pgvector cosine search with RBAC + metadata filters applied in the same SQL query."""
        # Let HNSW keep scanning until enough rows survive the permission filter (pgvector >= 0.8).
        self.db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        self.db.execute(text("SET LOCAL hnsw.ef_search = 200"))

        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        stmt = (
            select(DocumentChunk, Document, (1 - distance).label("similarity"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.processing_status == DocumentStatus.COMPLETED,
                Document.embedding_model == embedding_model,  # never mix embedding spaces
                accessible_documents_clause(user),
            )
        )
        f = filters or SearchFilters()
        if f.file_types:
            stmt = stmt.where(Document.file_type.in_(f.file_types))
        if f.department:
            stmt = stmt.where(Document.department == f.department)
        if f.uploaded_by:
            stmt = stmt.where(Document.uploaded_by == f.uploaded_by)
        if f.tags:
            stmt = stmt.where(Document.tags.overlap(f.tags))
        if f.date_from:
            stmt = stmt.where(Document.created_at >= f.date_from)
        if f.date_to:
            stmt = stmt.where(Document.created_at <= f.date_to)
        if f.document_ids:
            stmt = stmt.where(Document.id.in_(f.document_ids))
        stmt = stmt.order_by(distance).limit(top_k * 3)
        rows = self.db.execute(stmt).all()
        results = [(chunk, doc, float(sim)) for chunk, doc, sim in rows if sim >= threshold]
        return results[:top_k]
