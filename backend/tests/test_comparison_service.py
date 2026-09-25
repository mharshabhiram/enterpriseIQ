"""
Direct tests of app.services.comparison_service against the real database,
with an injected MockLLMProvider. Verifies RBAC reuse, guard rails
(self-comparison, unprocessed documents), the summarization fallback for
large documents, and that the structured JSON output always has all six
fixed categories regardless of what the LLM returned.
"""
import json
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
from app.security.password import hash_password
from app.services import comparison_service
from app.services.comparison_service import COMPARISON_CATEGORIES
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
    name: str = "Policy.txt",
    visibility=DocumentVisibility.PUBLIC,
    chunk_texts: list[str],
    status: ProcessingStatus = ProcessingStatus.COMPLETED,
):
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename=name,
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


_WELL_FORMED_RESPONSE = json.dumps(
    {
        "overview": "Leave allowance increased and a remote work clause was added.",
        "categories": [
            {"category": "Benefits", "differences": ["Annual leave increased from 15 to 20 days."]},
            {"category": "Policy Changes", "differences": ["New remote work clause added."]},
        ],
        "additions": ["Remote work clause"],
        "removals": [],
    }
)


async def test_compare_documents_direct_single_llm_call(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    doc_a = await _create_document_with_chunks(
        session, uploaded_by=manager.id, name="HR Policy 2025.txt", chunk_texts=["Employees get 15 days of leave."]
    )
    doc_b = await _create_document_with_chunks(
        session, uploaded_by=manager.id, name="HR Policy 2026.txt", chunk_texts=["Employees get 20 days of leave."]
    )

    llm = MockLLMProvider(response=_WELL_FORMED_RESPONSE)
    result = await comparison_service.compare_documents(session, manager, doc_a.id, doc_b.id, llm_provider=llm)

    assert llm.call_count == 1  # both docs are small enough to compare directly
    assert result.used_summaries is False
    assert [c["category"] for c in result.categories] == COMPARISON_CATEGORIES
    benefits = next(c for c in result.categories if c["category"] == "Benefits")
    assert benefits["differences"] == ["Annual leave increased from 15 to 20 days."]
    assert result.additions == ["Remote work clause"]

    # Verify both documents' names and content actually made it into the prompt.
    user_message = llm.last_messages[1]["content"]
    assert "HR Policy 2025.txt" in user_message
    assert "HR Policy 2026.txt" in user_message
    assert "15 days" in user_message
    assert "20 days" in user_message


async def test_compare_large_documents_falls_back_to_summaries(session: AsyncSession, monkeypatch) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    doc_a = await _create_document_with_chunks(
        session, uploaded_by=manager.id, chunk_texts=["A" * 100 for _ in range(5)]
    )
    doc_b = await _create_document_with_chunks(
        session, uploaded_by=manager.id, chunk_texts=["B" * 100 for _ in range(5)]
    )
    monkeypatch.setattr("app.services.comparison_service.settings.max_context_length", 200)
    monkeypatch.setattr("app.services.summarization_service.settings.max_context_length", 200)

    llm = MockLLMProvider(response=_WELL_FORMED_RESPONSE)
    result = await comparison_service.compare_documents(session, manager, doc_a.id, doc_b.id, llm_provider=llm)

    assert result.used_summaries is True
    # 5 chunks / small budget -> multiple MAP calls + 1 REDUCE call, per side, plus 1 final compare call.
    assert llm.call_count > 2


async def test_compare_rejects_comparing_document_with_itself(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    doc = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text"])

    with pytest.raises(InvalidOperationError):
        await comparison_service.compare_documents(session, manager, doc.id, doc.id, llm_provider=MockLLMProvider())


async def test_compare_rejects_unprocessed_document(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    doc_a = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text a"])
    doc_b = await _create_document_with_chunks(
        session, uploaded_by=manager.id, chunk_texts=["text b"], status=ProcessingStatus.PROCESSING
    )

    with pytest.raises(InvalidOperationError):
        await comparison_service.compare_documents(
            session, manager, doc_a.id, doc_b.id, llm_provider=MockLLMProvider()
        )


async def test_compare_reuses_document_visibility_rbac(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    doc_a = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text a"])
    doc_b = await _create_document_with_chunks(
        session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED, chunk_texts=["secret text b"]
    )
    outsider = await _create_user(session, role=UserRole.EMPLOYEE)

    with pytest.raises(DocumentNotFoundError):
        await comparison_service.compare_documents(
            session, outsider, doc_a.id, doc_b.id, llm_provider=MockLLMProvider()
        )


async def test_compare_handles_malformed_llm_response_gracefully(session: AsyncSession) -> None:
    manager = await _create_user(session, role=UserRole.MANAGER)
    doc_a = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text a"])
    doc_b = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text b"])

    llm = MockLLMProvider(response="This is not JSON at all, just prose about the differences.")
    result = await comparison_service.compare_documents(session, manager, doc_a.id, doc_b.id, llm_provider=llm)

    assert [c["category"] for c in result.categories] == COMPARISON_CATEGORIES
    important = next(c for c in result.categories if c["category"] == "Important Differences")
    assert "This is not JSON at all" in important["differences"][0]
