"""Ingestion pipeline: extract → clean → chunk → embed → store vectors → update metadata.

`process_document` runs outside the request (FastAPI BackgroundTasks) with its own
session; it is a plain function so it can be moved to Celery/RQ unchanged.
"""
import uuid

from app.ai.base import EmbeddingProvider
from app.config import get_settings
from app.database import SessionLocal
from app.exceptions import AppError
from app.ingestion.chunking import chunk_pages
from app.ingestion.extractors import extract
from app.logging_config import get_logger
from app.models import Document, DocumentChunk, DocumentStatus
from app.repositories.documents import DocumentRepository
from app.services.audit_service import AuditAction, record
from app.services.embedding_service import get_embedding_provider
from app.utils.files import absolute_path

log = get_logger(__name__)


def process_document(document_id: uuid.UUID, embedder: EmbeddingProvider | None = None) -> None:
    settings = get_settings()
    embedder = embedder or get_embedding_provider()
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        doc.processing_status = DocumentStatus.PROCESSING
        doc.processing_error = None
        db.commit()

        data = absolute_path(doc.storage_path).read_bytes()
        extracted = extract(data, doc.file_type)
        chunks = chunk_pages(extracted.pages, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise AppError("No readable text found. Scanned PDFs without a text layer are not supported.", code="NO_TEXT")

        # Title + section are prepended to the embedded text (not the stored text) to improve recall.
        texts = [f"{doc.title} — {c.section}\n{c.text}" if c.section else f"{doc.title}\n{c.text}" for c in chunks]
        vectors = embedder.embed(texts)
        DocumentRepository(db).replace_chunks(
            doc.id,
            [
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=c.index,
                    chunk_text=c.text,
                    page_number=c.page,
                    section=c.section[:255] if c.section else None,
                    embedding=v,
                )
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )
        doc.chunk_count = len(chunks)
        doc.page_count = extracted.page_count
        doc.embedding_model = embedder.model
        doc.embedding_dimensions = embedder.dimensions
        doc.processing_status = DocumentStatus.COMPLETED
        record(db, AuditAction.DOCUMENT_PROCESSED, doc.uploaded_by, "document", doc.id, {"chunks": len(chunks)}, commit=False)
        db.commit()
        log.info("document_processed", document_id=str(doc.id), chunks=len(chunks))
    except Exception as exc:  # noqa: BLE001 — any failure marks the document FAILED
        db.rollback()
        message = exc.message if isinstance(exc, AppError) else "Unexpected processing error."
        log.error("document_failed", document_id=str(document_id), error=message, exc_info=not isinstance(exc, AppError))
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.processing_status = DocumentStatus.FAILED
            doc.processing_error = message
            doc.chunk_count = 0
            record(db, AuditAction.DOCUMENT_FAILED, doc.uploaded_by, "document", doc.id, {"error": message}, commit=False)
            db.commit()
    finally:
        db.close()
