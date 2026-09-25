"""
Ingestion service - orchestrates the document processing pipeline (project
brief section 6): extraction -> chunking -> chunk storage -> embedding
generation -> status update.

Run as a FastAPI background task after the upload request returns (see
app.api.routes.documents), this opens its *own* DB session rather than
reusing the request's: FastAPI closes yield-based dependencies (committing
the request's session) before running background tasks, so the request
session is already gone by the time this executes.

Accepts an optional explicit `embedding_provider` purely for testability
(injecting a MockEmbeddingProvider bypasses network access entirely); the
route always calls this with the default, which resolves the configured
provider via app.ai.factory.get_embedding_provider.

A document reaching COMPLETED means "extracted, chunked, and embedded" -
i.e. actually ready for semantic search (Phase 5's search endpoint filters
to COMPLETED documents with a non-null embedding on each chunk).
"""
import logging
import uuid
from typing import Optional

from app.ai.embedding_provider import EmbeddingProvider
from app.config import settings
from app.db.session import async_session_factory
from app.ingestion.chunker import chunk_segments
from app.ingestion.extractors import extract_text
from app.ingestion.storage import build_storage_path
from app.models.enums import ProcessingStatus
from app.repositories import document_chunk_repository, document_repository
from app.services import embedding_service

logger = logging.getLogger(__name__)

_MAX_STORED_ERROR_LENGTH = 2000


async def process_document(document_id: uuid.UUID, *, embedding_provider: Optional[EmbeddingProvider] = None) -> None:
    async with async_session_factory() as session:
        document = await document_repository.get_by_id(session, document_id)
        if document is None:
            logger.warning("process_document: document %s no longer exists", document_id)
            return

        await document_repository.update_processing_result(
            session, document, status=ProcessingStatus.PROCESSING
        )
        await session.commit()

        try:
            path = build_storage_path(document.filename)
            segments = extract_text(path, document.file_type)
            if not segments:
                raise ValueError(
                    "No extractable text was found in this document. If it's a scanned or "
                    "image-only file, OCR is not yet supported."
                )

            chunks = chunk_segments(
                segments, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
            )
            if not chunks:
                raise ValueError("Text was extracted but produced no usable chunks.")

            chunks_created = await document_chunk_repository.bulk_create(
                session, document_id=document.id, chunks=chunks
            )
            await embedding_service.generate_embeddings(
                session, chunks_created, provider=embedding_provider
            )

            page_numbers = [s.page_number for s in segments if s.page_number is not None]
            page_count = max(page_numbers) if page_numbers else None

            await document_repository.update_processing_result(
                session,
                document,
                status=ProcessingStatus.COMPLETED,
                page_count=page_count,
                chunk_count=len(chunks),
            )
            await session.commit()
            logger.info("Document %s processed successfully: %d chunks", document.id, len(chunks))

        except Exception as exc:  # noqa: BLE001 - any failure here must land the doc in FAILED, never crash silently
            await session.rollback()
            # rollback expires in-memory object state, so re-fetch before touching it again
            document = await document_repository.get_by_id(session, document_id)
            if document is not None:
                await document_repository.update_processing_result(
                    session,
                    document,
                    status=ProcessingStatus.FAILED,
                    processing_error=str(exc)[:_MAX_STORED_ERROR_LENGTH],
                )
                await session.commit()
            logger.exception("Document %s processing failed", document_id)
