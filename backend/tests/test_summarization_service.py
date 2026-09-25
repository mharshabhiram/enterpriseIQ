"""
Direct tests of app.services.summarization_service against the real
database, with an injected MockLLMProvider. Verifies the direct-vs-map-
reduce strategy selection (the core deliverable of this phase) by counting
actual LLM calls, plus RBAC reuse and error handling.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.mock_llm_provider import MockLLMProvider
from app.config import settings
from app.models.document_chunk import DocumentChunk
from app.models.enums import DocumentVisibility, ProcessingStatus, UserRole
from app.repositories import document_repository, user_repository
from app.schemas.summary import SummaryType
from app.security.password import hash_password
from app.services import summarization_service
from app.utils.errors import DocumentNotFoundError, InvalidOperationError


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


async def _create_document_with_chunks(
    session: AsyncSession,
    *,
    uploaded_by,
    visibility=DocumentVisibility.PUBLIC,
    chunk_texts: list[str],
    status: ProcessingStatus = ProcessingStatus.COMPLETED,
):
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename="Policy.txt",
        file_type="txt",
        file_size=100,
        uploaded_by=uploaded_by,
        visibility=visibility,
    )
    document.processing_status = status
    document.chunk_count = len(chunk_texts)
    await session.flush()

    for index, text in enumerate(chunk_texts):
        session.add(DocumentChunk(document_id=document.id, chunk_index=index, chunk_text=text))
    await session.flush()
    return document


async def test_short_document_uses_direct_summarization_one_llm_call(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(
        session, uploaded_by=manager.id, chunk_texts=["A short policy document about vacation days."]
    )

    llm = MockLLMProvider(response="Short summary.")
    result = await summarization_service.summarize_document(
        session, manager, document.id, SummaryType.SHORT, llm_provider=llm
    )

    assert result.map_reduce_used is False
    assert llm.call_count == 1
    assert result.summary == "Short summary."
    assert result.chunk_count == 1


async def test_long_document_uses_map_reduce_multiple_llm_calls(session: AsyncSession, monkeypatch) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    # 5 chunks of 100 chars each = 500 chars total, well over a tiny budget.
    document = await _create_document_with_chunks(
        session, uploaded_by=manager.id, chunk_texts=["X" * 100 for _ in range(5)]
    )
    monkeypatch.setattr("app.services.summarization_service.settings.max_context_length", 150)

    llm = MockLLMProvider(response="partial or final summary")
    result = await summarization_service.summarize_document(
        session, manager, document.id, SummaryType.DETAILED, llm_provider=llm
    )

    assert result.map_reduce_used is True
    # With a 150-char budget and 100-char chunks, each group holds 1 chunk ->
    # 5 MAP calls + 1 REDUCE call = 6 total.
    assert llm.call_count == 6


async def test_summary_type_affects_the_prompt(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(
        session, uploaded_by=manager.id, chunk_texts=["Some policy text."]
    )

    llm = MockLLMProvider()
    await summarization_service.summarize_document(session, manager, document.id, SummaryType.EXECUTIVE, llm_provider=llm)
    system_prompt = llm.last_messages[0]["content"]
    assert "executive summary" in system_prompt.lower()


async def test_summarize_reuses_document_visibility_rbac(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(
        session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED, chunk_texts=["Secret text."]
    )
    outsider = await _create_user(session, role=UserRole.EMPLOYEE)

    with pytest.raises(DocumentNotFoundError):
        await summarization_service.summarize_document(
            session, outsider, document.id, SummaryType.SHORT, llm_provider=MockLLMProvider()
        )


async def test_summarize_rejects_unprocessed_document(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(
        session,
        uploaded_by=manager.id,
        chunk_texts=["text"],
        status=ProcessingStatus.PROCESSING,
    )

    with pytest.raises(InvalidOperationError):
        await summarization_service.summarize_document(
            session, manager, document.id, SummaryType.SHORT, llm_provider=MockLLMProvider()
        )
