"""
Direct tests of app.services.chat_service for two behaviors that are
awkward to exercise purely over HTTP: ordering conversations by recent
activity (requires controlling timing precisely), and a citation degrading
gracefully when its source document is deleted out from under it (requires
reaching into the DB to delete the document mid-test).
"""
import asyncio
import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.mock_embedding_provider import MockEmbeddingProvider
from app.ai.mock_llm_provider import MockLLMProvider
from app.config import settings
from app.models.document_chunk import DocumentChunk
from app.models.enums import DocumentVisibility, ProcessingStatus, UserRole
from app.repositories import document_repository, user_repository
from app.security.password import hash_password
from app.services import chat_service

_MOCK_EMBEDDING_PROVIDER = MockEmbeddingProvider(dimensions=settings.embedding_dimensions)


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


async def _create_user(session: AsyncSession, *, role: UserRole = UserRole.EMPLOYEE):
    return await user_repository.create(
        session, name="Test User", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("x"), role=role
    )


async def test_conversations_listed_most_recently_active_first(session: AsyncSession) -> None:
    user = await _create_user(session)
    llm = MockLLMProvider()

    turn_a = await chat_service.send_message(
        session, user, "First conversation", embedding_provider=_MOCK_EMBEDDING_PROVIDER, llm_provider=llm
    )
    await asyncio.sleep(0.01)
    turn_b = await chat_service.send_message(
        session, user, "Second conversation", embedding_provider=_MOCK_EMBEDDING_PROVIDER, llm_provider=llm
    )
    await asyncio.sleep(0.01)
    # Send a follow-up in conversation A - it should become the most recently active again.
    await chat_service.send_message(
        session,
        user,
        "Follow-up in first conversation",
        conversation_id=turn_a.conversation.id,
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )

    conversations = await chat_service.list_conversations(session, user)
    assert [c.id for c in conversations] == [turn_a.conversation.id, turn_b.conversation.id]


async def test_citation_degrades_gracefully_when_source_document_deleted(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename="Soon Deleted.txt",
        file_type="txt",
        file_size=10,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
    )
    document.processing_status = ProcessingStatus.COMPLETED
    document.chunk_count = 1
    await session.flush()

    text = "This document will be deleted after the conversation references it."
    vector = (await _MOCK_EMBEDDING_PROVIDER.embed([text]))[0]
    chunk = DocumentChunk(document_id=document.id, chunk_index=0, chunk_text=text, embedding=vector)
    session.add(chunk)
    await session.flush()

    llm = MockLLMProvider()
    turn = await chat_service.send_message(
        session,
        manager,
        text,
        similarity_threshold=0.0,
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )
    assert len(turn.sources) == 1

    # Now delete the document entirely (cascades to the chunk; the
    # MessageSource row survives via ON DELETE SET NULL on chunk_id).
    await document_repository.delete(session, document)

    conversation, messages = await chat_service.get_conversation_with_messages(session, manager, turn.conversation.id)
    assistant_message = next(m for m in messages if m.role.value == "assistant")
    assert len(assistant_message.sources) == 1
    source = assistant_message.sources[0]
    assert source.chunk_id is None  # SET NULL fired
    assert source.relevance_score is not None  # but the score itself is preserved
