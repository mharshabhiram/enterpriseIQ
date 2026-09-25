"""
End-to-end HTTP tests for the summarize and compare endpoints, relying on
LLM_PROVIDER=mock (set in tests/conftest.py) so the routes resolve their
provider through the real factory with no network access needed. Direct
service-level tests (map-reduce call counts, JSON normalization) live in
tests/test_summarization_service.py and tests/test_comparison_service.py;
these confirm the HTTP layer, RBAC, and response shapes.
"""
import json
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_db
from app.config import settings
from app.main import app
from app.models.document_chunk import DocumentChunk
from app.models.enums import DocumentVisibility, ProcessingStatus, UserRole
from app.repositories import document_repository, user_repository
from app.security.password import hash_password


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


async def _create_document_with_chunks(
    session: AsyncSession, *, uploaded_by, name="Policy.txt", visibility=DocumentVisibility.PUBLIC, chunk_texts
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
    document.processing_status = ProcessingStatus.COMPLETED
    document.chunk_count = len(chunk_texts)
    await session.flush()
    for index, text in enumerate(chunk_texts):
        session.add(DocumentChunk(document_id=document.id, chunk_index=index, chunk_text=text))
    await session.flush()
    return document


# --- Summarize ---


async def test_summarize_document(client: AsyncClient, session: AsyncSession) -> None:
    manager, email, password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(
        session, uploaded_by=manager.id, chunk_texts=["Employees receive 20 days of annual leave."]
    )

    token = await _login(client, email, password)
    response = await client.post(
        f"/api/documents/{document.id}/summarize", headers=_auth(token), json={"summary_type": "SHORT"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_id"] == str(document.id)
    assert body["document_name"] == "Policy.txt"
    assert body["summary_type"] == "SHORT"
    assert body["summary"]
    assert body["map_reduce_used"] is False


async def test_summarize_defaults_to_short(client: AsyncClient, session: AsyncSession) -> None:
    manager, email, password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["Some text."])

    token = await _login(client, email, password)
    response = await client.post(f"/api/documents/{document.id}/summarize", headers=_auth(token), json={})
    assert response.status_code == 200
    assert response.json()["summary_type"] == "SHORT"


async def test_summarize_restricted_document_without_access_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(
        session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED, chunk_texts=["secret"]
    )

    outsider, outsider_email, outsider_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, outsider_email, outsider_password)

    response = await client.post(f"/api/documents/{document.id}/summarize", headers=_auth(token), json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_summarize_nonexistent_document_returns_404(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session)
    token = await _login(client, email, password)

    response = await client.post(f"/api/documents/{uuid.uuid4()}/summarize", headers=_auth(token), json={})
    assert response.status_code == 404


async def test_summarize_still_processing_document_returns_400(client: AsyncClient, session: AsyncSession) -> None:
    manager, email, password = await _create_user(session, role=UserRole.MANAGER)
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename="Still Processing.txt",
        file_type="txt",
        file_size=10,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
    )  # processing_status defaults to UPLOADED

    token = await _login(client, email, password)
    response = await client.post(f"/api/documents/{document.id}/summarize", headers=_auth(token), json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OPERATION"


# --- Compare ---


async def test_compare_documents(client: AsyncClient, session: AsyncSession) -> None:
    manager, email, password = await _create_user(session, role=UserRole.MANAGER)
    doc_a = await _create_document_with_chunks(
        session, uploaded_by=manager.id, name="HR Policy 2025.txt", chunk_texts=["Leave is 15 days."]
    )
    doc_b = await _create_document_with_chunks(
        session, uploaded_by=manager.id, name="HR Policy 2026.txt", chunk_texts=["Leave is 20 days."]
    )

    token = await _login(client, email, password)
    response = await client.post(
        "/api/documents/compare",
        headers=_auth(token),
        json={"document_id_a": str(doc_a.id), "document_id_b": str(doc_b.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_a"]["name"] == "HR Policy 2025.txt"
    assert body["document_b"]["name"] == "HR Policy 2026.txt"
    assert len(body["categories"]) == 6
    assert {c["category"] for c in body["categories"]} == {
        "Policy Changes",
        "Dates",
        "Responsibilities",
        "Eligibility",
        "Benefits",
        "Important Differences",
    }
    assert isinstance(body["additions"], list)
    assert isinstance(body["removals"], list)
    assert "used_summaries" in body


async def test_compare_same_document_returns_400(client: AsyncClient, session: AsyncSession) -> None:
    manager, email, password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text"])

    token = await _login(client, email, password)
    response = await client.post(
        "/api/documents/compare",
        headers=_auth(token),
        json={"document_id_a": str(document.id), "document_id_b": str(document.id)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OPERATION"


async def test_compare_document_without_access_returns_404(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    doc_a = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text a"])
    doc_b = await _create_document_with_chunks(
        session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED, chunk_texts=["secret b"]
    )

    outsider, outsider_email, outsider_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, outsider_email, outsider_password)

    response = await client.post(
        "/api/documents/compare",
        headers=_auth(token),
        json={"document_id_a": str(doc_a.id), "document_id_b": str(doc_b.id)},
    )
    assert response.status_code == 404


async def test_summarize_requires_auth(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document_with_chunks(session, uploaded_by=manager.id, chunk_texts=["text"])

    response = await client.post(f"/api/documents/{document.id}/summarize", json={})
    assert response.status_code in (401, 403)


async def test_compare_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/documents/compare",
        json={"document_id_a": str(uuid.uuid4()), "document_id_b": str(uuid.uuid4())},
    )
    assert response.status_code in (401, 403)
