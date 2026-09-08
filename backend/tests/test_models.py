"""
Integration tests for the Phase 2 ORM models against a real PostgreSQL +
pgvector database.

These deliberately run against a real database rather than mocking it out:
the whole point of this phase is to prove the cascade behavior and the
`vector` column actually work, not just that the Python objects construct
without error. Requires DATABASE_URL to point at a reachable Postgres with
the Phase 2 migration applied (`alembic upgrade head`) - e.g. the
docker-compose `postgres` service, or a local instance.

Each test runs inside a transaction that's rolled back afterwards, so
re-running the suite never leaves stray rows behind.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import (
    Conversation,
    Document,
    DocumentChunk,
    DocumentPermission,
    Message,
    MessageSource,
    User,
)
from app.models.enums import DocumentVisibility, GranteeType, MessageRole, ProcessingStatus, UserRole


@pytest_asyncio.fixture
async def session():
    """
    A session bound to a connection whose transaction is always rolled back.

    Uses a fresh NullPool engine per test rather than the app's shared
    `app.db.session.engine` singleton: asyncpg connections are bound to the
    event loop that created them, and pytest-asyncio's default function-
    scoped event loop means a pooled connection from one test's loop breaks
    when reused in the next test's loop. A disposable per-test engine with
    no pooling sidesteps that entirely.
    """
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


async def _make_user(session: AsyncSession, role: UserRole = UserRole.EMPLOYEE) -> User:
    user = User(
        name="Test User",
        email=f"{uuid.uuid4()}@example.com",
        password_hash="not-a-real-hash",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def test_create_user_defaults(session: AsyncSession) -> None:
    user = await _make_user(session, role=UserRole.ADMIN)
    assert user.id is not None
    assert user.is_active is True
    assert user.role == UserRole.ADMIN


async def test_document_chunk_stores_and_retrieves_embedding(session: AsyncSession) -> None:
    user = await _make_user(session)
    document = Document(
        filename="stored-name.pdf",
        original_filename="Employee Handbook.pdf",
        file_type="pdf",
        file_size=1024,
        uploaded_by=user.id,
        processing_status=ProcessingStatus.COMPLETED,
        visibility=DocumentVisibility.PUBLIC,
    )
    session.add(document)
    await session.flush()

    embedding = [0.001 * i for i in range(settings.embedding_dimensions)]
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        chunk_text="Employees receive 20 days of annual leave.",
        page_number=24,
        embedding=embedding,
    )
    session.add(chunk)
    await session.flush()
    await session.refresh(chunk)

    assert chunk.id is not None
    assert len(chunk.embedding) == settings.embedding_dimensions
    assert chunk.embedding[1] == pytest.approx(0.001)


async def test_deleting_document_cascades_to_chunks_and_permissions(session: AsyncSession) -> None:
    user = await _make_user(session)
    document = Document(
        filename="a.pdf",
        original_filename="a.pdf",
        file_type="pdf",
        file_size=10,
        uploaded_by=user.id,
        visibility=DocumentVisibility.RESTRICTED,
    )
    session.add(document)
    await session.flush()

    chunk = DocumentChunk(document_id=document.id, chunk_index=0, chunk_text="hello")
    permission = DocumentPermission(
        document_id=document.id, grantee_type=GranteeType.ROLE, role=UserRole.MANAGER
    )
    session.add_all([chunk, permission])
    await session.flush()

    await session.delete(document)
    await session.flush()

    remaining_chunks = (
        await session.execute(select(DocumentChunk).where(DocumentChunk.document_id == document.id))
    ).scalars().all()
    remaining_permissions = (
        await session.execute(select(DocumentPermission).where(DocumentPermission.document_id == document.id))
    ).scalars().all()

    assert remaining_chunks == []
    assert remaining_permissions == []


async def test_deleting_user_sets_document_uploaded_by_null(session: AsyncSession) -> None:
    """Documents must outlive the account that uploaded them (see Document.uploaded_by)."""
    user = await _make_user(session)
    document = Document(
        filename="b.pdf",
        original_filename="b.pdf",
        file_type="pdf",
        file_size=10,
        uploaded_by=user.id,
        visibility=DocumentVisibility.PUBLIC,
    )
    session.add(document)
    await session.flush()

    await session.delete(user)
    await session.flush()
    await session.refresh(document)

    assert document.uploaded_by is None


async def test_document_permission_grantee_check_constraint(session: AsyncSession) -> None:
    """A ROLE grant with no role set must be rejected at the database level."""
    document = Document(
        filename="c.pdf",
        original_filename="c.pdf",
        file_type="pdf",
        file_size=1,
        visibility=DocumentVisibility.RESTRICTED,
    )
    session.add(document)
    await session.flush()

    bad_permission = DocumentPermission(document_id=document.id, grantee_type=GranteeType.ROLE, role=None)
    session.add(bad_permission)

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_conversation_message_and_source_chain(session: AsyncSession) -> None:
    user = await _make_user(session)
    document = Document(
        filename="d.pdf",
        original_filename="d.pdf",
        file_type="pdf",
        file_size=1,
        uploaded_by=user.id,
        visibility=DocumentVisibility.PUBLIC,
    )
    session.add(document)
    await session.flush()

    chunk = DocumentChunk(document_id=document.id, chunk_index=0, chunk_text="20 days leave")
    session.add(chunk)
    await session.flush()

    conversation = Conversation(user_id=user.id, title="Leave policy question")
    session.add(conversation)
    await session.flush()

    question = Message(conversation_id=conversation.id, role=MessageRole.USER, content="How many leave days?")
    answer = Message(conversation_id=conversation.id, role=MessageRole.ASSISTANT, content="20 days per year.")
    session.add_all([question, answer])
    await session.flush()

    source = MessageSource(message_id=answer.id, chunk_id=chunk.id, relevance_score=0.93)
    session.add(source)
    await session.flush()

    assert answer.role == MessageRole.ASSISTANT
    assert answer.role.value == "assistant"
    assert source.relevance_score == pytest.approx(0.93)
