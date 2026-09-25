"""
Direct tests of app.services.rag_service against the real Postgres+pgvector
database, with injected Mock providers (deterministic, offline). These
verify the RAG pipeline logic itself - the no-context safety behavior,
prompt/context construction, and citation accuracy - independent of the
HTTP layer (see tests/test_chat.py for the end-to-end HTTP tests).
"""
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
from app.services import rag_service

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
        session,
        name="Test User",
        email=f"{uuid.uuid4()}@example.com",
        password_hash=hash_password("x"),
        role=role,
    )


async def _create_embedded_document(
    session: AsyncSession, *, uploaded_by, visibility=DocumentVisibility.PUBLIC, chunk_texts: list[str]
):
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename="Employee Handbook.txt",
        file_type="txt",
        file_size=100,
        uploaded_by=uploaded_by,
        visibility=visibility,
    )
    document.processing_status = ProcessingStatus.COMPLETED
    document.chunk_count = len(chunk_texts)
    await session.flush()

    chunks = []
    for index, text in enumerate(chunk_texts):
        vector = (await _MOCK_EMBEDDING_PROVIDER.embed([text]))[0]
        chunk = DocumentChunk(
            document_id=document.id, chunk_index=index, chunk_text=text, page_number=index + 1, embedding=vector
        )
        session.add(chunk)
        chunks.append(chunk)
    await session.flush()
    return document, chunks


# --- No-context safety ---


async def test_no_context_found_returns_safe_answer_without_calling_llm(session: AsyncSession) -> None:
    user = await _create_user(session)
    llm = MockLLMProvider()

    result = await rag_service.answer_question(
        session,
        user,
        "What is the meaning of life?",
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )

    assert result.answer == rag_service.NO_CONTEXT_ANSWER
    assert result.sources == []
    assert llm.call_count == 0  # the LLM must never be invoked when there's nothing to ground it


async def test_whitespace_only_question_returns_safe_answer_without_search(session: AsyncSession) -> None:
    user = await _create_user(session)
    llm = MockLLMProvider()

    result = await rag_service.answer_question(
        session, user, "   ", embedding_provider=_MOCK_EMBEDDING_PROVIDER, llm_provider=llm
    )

    assert result.answer == rag_service.NO_CONTEXT_ANSWER
    assert llm.call_count == 0


async def test_restricted_document_without_access_behaves_like_no_context(session: AsyncSession) -> None:
    """RBAC filtering happens inside retrieval - an inaccessible chunk is invisible to the LLM too."""
    manager = await _create_user(session, role=UserRole.MANAGER)
    await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.RESTRICTED,
        chunk_texts=["Confidential merger and acquisition details for Q3."],
    )

    outsider = await _create_user(session, role=UserRole.EMPLOYEE)
    llm = MockLLMProvider()

    result = await rag_service.answer_question(
        session,
        outsider,
        "Confidential merger and acquisition details for Q3.",
        similarity_threshold=0.0,
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )

    assert result.answer == rag_service.NO_CONTEXT_ANSWER
    assert llm.call_count == 0


# --- Context found: prompt construction and citations ---


async def test_context_found_calls_llm_with_context_and_returns_citations(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        chunk_texts=["Employees receive 20 days of annual leave per calendar year."],
    )

    llm = MockLLMProvider(response="Employees get 20 days of leave per year.")
    result = await rag_service.answer_question(
        session,
        manager,
        "Employees receive 20 days of annual leave per calendar year.",
        similarity_threshold=0.0,
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )

    assert result.answer == "Employees get 20 days of leave per year."
    assert llm.call_count == 1
    assert len(result.sources) == 1
    assert result.sources[0].chunk_id == chunks[0].id
    assert result.sources[0].document_id == document.id

    # Verify actual prompt construction: the retrieved excerpt and document
    # name must appear in the user message sent to the LLM.
    system_message, user_message = llm.last_messages
    assert system_message["role"] == "system"
    assert "only" in system_message["content"].lower()
    assert user_message["role"] == "user"
    assert "Employees receive 20 days of annual leave per calendar year." in user_message["content"]
    assert "Employee Handbook.txt" in user_message["content"]
    assert "page 1" in user_message["content"]


async def test_multiple_sources_all_labeled_and_cited(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    identical_text = "Remote work policy details for engineering staff."
    document, chunks = await _create_embedded_document(
        session, uploaded_by=manager.id, chunk_texts=[identical_text, identical_text, identical_text]
    )

    llm = MockLLMProvider()
    result = await rag_service.answer_question(
        session,
        manager,
        identical_text,
        similarity_threshold=0.0,
        top_k=3,
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )

    assert len(result.sources) == 3
    user_message = llm.last_messages[1]["content"]
    assert "[Source 1:" in user_message
    assert "[Source 2:" in user_message
    assert "[Source 3:" in user_message


# --- Context truncation respects MAX_CONTEXT_LENGTH ---


async def test_context_truncated_to_max_context_length(session: AsyncSession, monkeypatch) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    identical_text = "A" * 200  # long chunk text
    document, chunks = await _create_embedded_document(
        session, uploaded_by=manager.id, chunk_texts=[identical_text] * 5
    )

    # Small enough budget that only the first chunk (always included) fits comfortably,
    # but too small to fit a second ~200+ char block on top of it.
    monkeypatch.setattr("app.services.rag_service.settings.max_context_length", 250)

    llm = MockLLMProvider()
    result = await rag_service.answer_question(
        session,
        manager,
        identical_text,
        similarity_threshold=0.0,
        top_k=5,
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )

    # At least one source is always included even if it alone exceeds budget,
    # but not all 5 - the budget must have actually constrained inclusion.
    assert 1 <= len(result.sources) < 5


async def test_at_least_one_source_included_even_if_it_exceeds_budget(
    session: AsyncSession, monkeypatch
) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    long_text = "B" * 5000
    document, chunks = await _create_embedded_document(session, uploaded_by=manager.id, chunk_texts=[long_text])

    monkeypatch.setattr("app.services.rag_service.settings.max_context_length", 10)  # absurdly small

    llm = MockLLMProvider()
    result = await rag_service.answer_question(
        session,
        manager,
        long_text,
        similarity_threshold=0.0,
        embedding_provider=_MOCK_EMBEDDING_PROVIDER,
        llm_provider=llm,
    )

    assert len(result.sources) == 1
    assert llm.call_count == 1
