"""Tests for app.services.embedding_service."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.mock_embedding_provider import MockEmbeddingProvider
from app.config import settings
from app.models.document_chunk import DocumentChunk
from app.models.enums import DocumentVisibility, UserRole
from app.repositories import document_repository, user_repository
from app.security.password import hash_password
from app.services import embedding_service
from app.utils.errors import EmbeddingProviderError


@pytest_asyncio.fixture
async def session():
    test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with test_engine.connect() as connection:
        trans = await connection.begin()
        async_session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield async_session
        finally:
            await async_session.close()
            await trans.rollback()
    await test_engine.dispose()


class _WrongCountProvider(EmbeddingProvider):
    """A deliberately broken provider that returns the wrong number of vectors."""

    async def embed(self, texts):
        return [[0.0] * settings.embedding_dimensions]  # always returns exactly 1, regardless of input


async def _make_document_with_chunks(session: AsyncSession, texts: list[str]):
    user = await user_repository.create(
        session,
        name="Uploader",
        email=f"{uuid.uuid4()}@example.com",
        password_hash=hash_password("x"),
        role=UserRole.MANAGER,
    )
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename="doc.txt",
        file_type="txt",
        file_size=10,
        uploaded_by=user.id,
        visibility=DocumentVisibility.PUBLIC,
    )
    chunks = [
        DocumentChunk(document_id=document.id, chunk_index=i, chunk_text=text)
        for i, text in enumerate(texts)
    ]
    session.add_all(chunks)
    await session.flush()
    return document, chunks


async def test_generate_embeddings_fills_in_vectors(session: AsyncSession) -> None:
    _, chunks = await _make_document_with_chunks(session, ["first chunk", "second chunk"])
    assert all(chunk.embedding is None for chunk in chunks)

    provider = MockEmbeddingProvider(dimensions=settings.embedding_dimensions)
    await embedding_service.generate_embeddings(session, chunks, provider=provider)

    assert all(chunk.embedding is not None for chunk in chunks)
    assert all(len(chunk.embedding) == settings.embedding_dimensions for chunk in chunks)
    # different texts -> different vectors
    assert chunks[0].embedding != chunks[1].embedding


async def test_generate_embeddings_no_op_on_empty_list(session: AsyncSession) -> None:
    # Should not raise or call the provider at all.
    await embedding_service.generate_embeddings(session, [], provider=MockEmbeddingProvider(dimensions=8))


async def test_generate_embeddings_batches_large_chunk_lists(session: AsyncSession) -> None:
    """More chunks than the internal batch size must still all get embedded."""
    texts = [f"chunk number {i}" for i in range(250)]  # > _BATCH_SIZE (100)
    _, chunks = await _make_document_with_chunks(session, texts)

    # Must match settings.embedding_dimensions - the document_chunks.embedding
    # column has a fixed dimension (set at migration time) and will reject
    # vectors of any other length.
    provider = MockEmbeddingProvider(dimensions=settings.embedding_dimensions)
    await embedding_service.generate_embeddings(session, chunks, provider=provider)

    assert all(chunk.embedding is not None for chunk in chunks)
    assert len({tuple(chunk.embedding) for chunk in chunks}) == 250  # all distinct


async def test_generate_embeddings_raises_on_vector_count_mismatch(session: AsyncSession) -> None:
    _, chunks = await _make_document_with_chunks(session, ["a", "b", "c"])
    with pytest.raises(EmbeddingProviderError):
        await embedding_service.generate_embeddings(session, chunks, provider=_WrongCountProvider())
