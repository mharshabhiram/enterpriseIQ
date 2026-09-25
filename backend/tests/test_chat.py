"""
End-to-end HTTP tests for POST /api/chat, relying on EMBEDDING_PROVIDER=mock
and LLM_PROVIDER=mock (set in tests/conftest.py) so the whole route resolves
its providers through the real factory with no network access needed.
Direct rag_service-level tests (prompt construction, citation accuracy,
truncation) live in tests/test_rag_service.py; these confirm the HTTP layer
wires everything together correctly.
"""
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.mock_embedding_provider import MockEmbeddingProvider
from app.api.dependencies import get_db
from app.config import settings
from app.main import app
from app.models.document_chunk import DocumentChunk
from app.models.enums import DocumentVisibility, ProcessingStatus, UserRole
from app.repositories import document_repository, user_repository
from app.security.password import hash_password

_MOCK_PROVIDER = MockEmbeddingProvider(dimensions=settings.embedding_dimensions)


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


@pytest_asyncio.fixture
async def client(session: AsyncSession):
    async def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _create_user(session: AsyncSession, *, role: UserRole = UserRole.EMPLOYEE):
    email = f"{uuid.uuid4()}@example.com"
    password = "Password123!"
    user = await user_repository.create(
        session, name="Test User", email=email, password_hash=hash_password(password), role=role
    )
    return user, email, password


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_embedded_document(session: AsyncSession, *, uploaded_by, visibility, chunk_texts):
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename="HR Policy.txt",
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
        vector = (await _MOCK_PROVIDER.embed([text]))[0]
        chunk = DocumentChunk(document_id=document.id, chunk_index=index, chunk_text=text, embedding=vector)
        session.add(chunk)
        chunks.append(chunk)
    await session.flush()
    return document, chunks


async def test_chat_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/chat", json={"question": "What is the leave policy?"})
    assert response.status_code in (401, 403)


async def test_chat_with_no_relevant_documents_returns_safe_answer(
    client: AsyncClient, session: AsyncSession
) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    response = await client.post(
        "/api/chat", headers=_auth(token), json={"question": "What is the meaning of life?"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sources"] == []
    assert "couldn't find" in body["answer"].lower()


async def test_chat_returns_answer_with_citations(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
        chunk_texts=["All full-time employees are entitled to 20 days of paid annual leave."],
    )

    token = await _login(client, manager_email, manager_password)
    response = await client.post(
        "/api/chat",
        headers=_auth(token),
        json={
            "question": "All full-time employees are entitled to 20 days of paid annual leave.",
            "similarity_threshold": 0.0,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"]  # mock LLM's canned response, non-empty
    assert uuid.UUID(body["conversation_id"])
    assert uuid.UUID(body["message_id"])
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["chunk_id"] == str(chunks[0].id)
    assert source["document_id"] == str(document.id)
    assert source["document_name"] == "HR Policy.txt"
    assert 0.0 <= source["relevance_score"] <= 1.0


async def test_chat_excludes_restricted_document_without_access(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.RESTRICTED,
        chunk_texts=["Highly confidential executive severance terms."],
    )

    outsider, outsider_email, outsider_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, outsider_email, outsider_password)

    response = await client.post(
        "/api/chat",
        headers=_auth(token),
        json={"question": "Highly confidential executive severance terms.", "similarity_threshold": 0.0},
    )
    assert response.status_code == 200
    assert response.json()["sources"] == []


async def test_chat_rejects_whitespace_only_question(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    response = await client.post("/api/chat", headers=_auth(token), json={"question": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_chat_rejects_empty_question(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    response = await client.post("/api/chat", headers=_auth(token), json={"question": ""})
    assert response.status_code == 422


# --- Phase 7: conversation persistence ---


async def test_second_message_without_conversation_id_starts_a_new_conversation(
    client: AsyncClient, session: AsyncSession
) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    first = await client.post("/api/chat", headers=_auth(token), json={"question": "First question?"})
    second = await client.post("/api/chat", headers=_auth(token), json={"question": "Second question?"})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["conversation_id"] != second.json()["conversation_id"]


async def test_conversation_id_continues_the_same_conversation(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    first = await client.post("/api/chat", headers=_auth(token), json={"question": "First question?"})
    conversation_id = first.json()["conversation_id"]

    second = await client.post(
        "/api/chat",
        headers=_auth(token),
        json={"question": "Follow-up question?", "conversation_id": conversation_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id


async def test_chat_with_nonexistent_conversation_id_returns_404(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    response = await client.post(
        "/api/chat", headers=_auth(token), json={"question": "hi", "conversation_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_cannot_continue_another_users_conversation(client: AsyncClient, session: AsyncSession) -> None:
    _, email_a, password_a = await _create_user(session)
    _, email_b, password_b = await _create_user(session)
    token_a = await _login(client, email_a, password_a)
    token_b = await _login(client, email_b, password_b)

    started = await client.post("/api/chat", headers=_auth(token_a), json={"question": "User A's question"})
    conversation_id = started.json()["conversation_id"]

    hijack_attempt = await client.post(
        "/api/chat",
        headers=_auth(token_b),
        json={"question": "User B trying to hijack", "conversation_id": conversation_id},
    )
    assert hijack_attempt.status_code == 404
    assert hijack_attempt.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_list_conversations_only_shows_own_conversations(client: AsyncClient, session: AsyncSession) -> None:
    _, email_a, password_a = await _create_user(session)
    _, email_b, password_b = await _create_user(session)
    token_a = await _login(client, email_a, password_a)
    token_b = await _login(client, email_b, password_b)

    await client.post("/api/chat", headers=_auth(token_a), json={"question": "Question from A"})
    await client.post("/api/chat", headers=_auth(token_b), json={"question": "Question from B"})

    response = await client.get("/api/conversations", headers=_auth(token_a))
    assert response.status_code == 200
    conversations = response.json()
    assert len(conversations) == 1
    assert conversations[0]["title"] == "Question from A"


async def test_conversation_title_derived_from_first_question_only(
    client: AsyncClient, session: AsyncSession
) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    first = await client.post("/api/chat", headers=_auth(token), json={"question": "What is the leave policy?"})
    conversation_id = first.json()["conversation_id"]
    await client.post(
        "/api/chat",
        headers=_auth(token),
        json={"question": "And what about sick leave?", "conversation_id": conversation_id},
    )

    detail = await client.get(f"/api/conversations/{conversation_id}", headers=_auth(token))
    assert detail.status_code == 200
    assert detail.json()["title"] == "What is the leave policy?"  # unchanged by the second question


async def test_get_conversation_detail_includes_full_message_history_and_sources(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
        chunk_texts=["Parental leave is 12 weeks paid for primary caregivers."],
    )

    token = await _login(client, manager_email, manager_password)
    response = await client.post(
        "/api/chat",
        headers=_auth(token),
        json={
            "question": "Parental leave is 12 weeks paid for primary caregivers.",
            "similarity_threshold": 0.0,
        },
    )
    conversation_id = response.json()["conversation_id"]

    detail = await client.get(f"/api/conversations/{conversation_id}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Parental leave is 12 weeks paid for primary caregivers."
    assert body["messages"][0]["sources"] == []
    assert body["messages"][1]["role"] == "assistant"
    assert len(body["messages"][1]["sources"]) == 1
    source = body["messages"][1]["sources"][0]
    assert source["chunk_id"] == str(chunks[0].id)
    assert source["document_name"] == "HR Policy.txt"


async def test_cannot_view_another_users_conversation(client: AsyncClient, session: AsyncSession) -> None:
    _, email_a, password_a = await _create_user(session)
    _, email_b, password_b = await _create_user(session)
    token_a = await _login(client, email_a, password_a)
    token_b = await _login(client, email_b, password_b)

    started = await client.post("/api/chat", headers=_auth(token_a), json={"question": "Private question"})
    conversation_id = started.json()["conversation_id"]

    response = await client.get(f"/api/conversations/{conversation_id}", headers=_auth(token_b))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_admin_cannot_view_another_users_conversation(client: AsyncClient, session: AsyncSession) -> None:
    """Conversations are private even from admins - not organizational data."""
    _, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    token = await _login(client, email, password)
    admin_token = await _login(client, admin_email, admin_password)

    started = await client.post("/api/chat", headers=_auth(token), json={"question": "Employee's private question"})
    conversation_id = started.json()["conversation_id"]

    response = await client.get(f"/api/conversations/{conversation_id}", headers=_auth(admin_token))
    assert response.status_code == 404


async def test_delete_conversation(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    started = await client.post("/api/chat", headers=_auth(token), json={"question": "To be deleted"})
    conversation_id = started.json()["conversation_id"]

    delete_response = await client.delete(f"/api/conversations/{conversation_id}", headers=_auth(token))
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/conversations/{conversation_id}", headers=_auth(token))
    assert get_response.status_code == 404


async def test_cannot_delete_another_users_conversation(client: AsyncClient, session: AsyncSession) -> None:
    _, email_a, password_a = await _create_user(session)
    _, email_b, password_b = await _create_user(session)
    token_a = await _login(client, email_a, password_a)
    token_b = await _login(client, email_b, password_b)

    started = await client.post("/api/chat", headers=_auth(token_a), json={"question": "A's conversation"})
    conversation_id = started.json()["conversation_id"]

    response = await client.delete(f"/api/conversations/{conversation_id}", headers=_auth(token_b))
    assert response.status_code == 404

    # still exists for the owner
    still_there = await client.get(f"/api/conversations/{conversation_id}", headers=_auth(token_a))
    assert still_there.status_code == 200
