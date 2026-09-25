"""
Integration tests for Phase 5: pgvector similarity search and its RBAC
filtering. Uses the real Postgres+pgvector database and the real
MockEmbeddingProvider (deterministic, no network) - both the search
infrastructure (ranking, thresholding, filters) and the RBAC enforcement
inside the query are exercised for real, not mocked out.

Chunks are inserted directly (with pre-computed mock embeddings) via the
rolled-back-transaction pattern from test_documents.py, since these tests
care about the search *query* logic, not the ingestion pipeline (already
covered end-to-end in test_ingestion.py).
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
from app.models.document_permission import DocumentPermission
from app.models.enums import DocumentVisibility, GranteeType, ProcessingStatus, UserRole
from app.repositories import document_repository, user_repository
from app.security.password import hash_password
from app.services import retrieval_service

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


async def _create_user(session: AsyncSession, *, role: UserRole, password: str = "Password123!"):
    email = f"{uuid.uuid4()}@example.com"
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


async def _create_embedded_document(
    session: AsyncSession,
    *,
    uploaded_by,
    visibility=DocumentVisibility.RESTRICTED,
    chunk_texts: list[str],
) -> tuple:
    document = await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.txt",
        original_filename="policy.txt",
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
        chunk = DocumentChunk(
            document_id=document.id, chunk_index=index, chunk_text=text, embedding=vector
        )
        session.add(chunk)
        chunks.append(chunk)
    await session.flush()
    return document, chunks


# --- Core ranking behavior ---


async def test_search_ranks_exact_text_match_highest(client: AsyncClient, session: AsyncSession) -> None:
    """
    With a deterministic mock provider, searching for the *exact* text of a
    chunk must return that chunk first with relevance_score == 1.0 (cosine
    distance 0) - this proves the pgvector ORDER BY / ranking logic itself
    is correct, independent of real embedding quality.
    """
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
        chunk_texts=["Employees receive 20 days of annual leave.", "Remote work needs manager approval."],
    )

    token = await _login(client, manager_email, manager_password)
    response = await client.post(
        "/api/search",
        headers=_auth(token),
        json={"query": "Employees receive 20 days of annual leave.", "similarity_threshold": 0.0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) >= 1
    top = body["results"][0]
    assert top["chunk_id"] == str(chunks[0].id)
    assert top["relevance_score"] == 1.0
    assert top["document_id"] == str(document.id)


async def test_search_respects_top_k(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    # Identical text -> identical mock vector -> guaranteed similarity 1.0 for
    # all five chunks, so top_k's LIMIT is what caps the count, deterministically
    # (distinct random mock vectors would have ~random pairwise similarity,
    # which could flakily pass or fail a fixed threshold).
    identical_text = "Workplace conduct policy statement."
    await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
        chunk_texts=[identical_text] * 5,
    )

    token = await _login(client, manager_email, manager_password)
    response = await client.post(
        "/api/search",
        headers=_auth(token),
        json={"query": identical_text, "top_k": 2, "similarity_threshold": 0.0},
    )
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2


async def test_search_excludes_uncompleted_documents(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
        chunk_texts=["A very specific unique phrase about kangaroo migration patterns."],
    )
    # Simulate a document still mid-processing - its chunks must not appear in results
    document.processing_status = ProcessingStatus.PROCESSING
    await session.flush()

    token = await _login(client, manager_email, manager_password)
    response = await client.post(
        "/api/search",
        headers=_auth(token),
        json={
            "query": "A very specific unique phrase about kangaroo migration patterns.",
            "similarity_threshold": 0.0,
        },
    )
    assert response.status_code == 200
    result_chunk_ids = {r["chunk_id"] for r in response.json()["results"]}
    assert str(chunks[0].id) not in result_chunk_ids


# --- RBAC enforcement inside the search query ---


async def test_search_excludes_restricted_documents_without_access(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.RESTRICTED,
        chunk_texts=["Confidential executive compensation details for fiscal year planning."],
    )

    other, other_email, other_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, other_email, other_password)

    response = await client.post(
        "/api/search",
        headers=_auth(token),
        json={
            "query": "Confidential executive compensation details for fiscal year planning.",
            "similarity_threshold": 0.0,
        },
    )
    assert response.status_code == 200
    result_chunk_ids = {r["chunk_id"] for r in response.json()["results"]}
    assert str(chunks[0].id) not in result_chunk_ids


async def test_search_includes_restricted_document_after_role_grant(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.RESTRICTED,
        chunk_texts=["Special onboarding checklist for new engineering hires."],
    )
    session.add(DocumentPermission(document_id=document.id, grantee_type=GranteeType.ROLE, role=UserRole.EMPLOYEE))
    await session.flush()

    employee, employee_email, employee_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, employee_email, employee_password)

    response = await client.post(
        "/api/search",
        headers=_auth(token),
        json={"query": "Special onboarding checklist for new engineering hires.", "similarity_threshold": 0.0},
    )
    assert response.status_code == 200
    result_chunk_ids = {r["chunk_id"] for r in response.json()["results"]}
    assert str(chunks[0].id) in result_chunk_ids


async def test_admin_search_sees_all_documents(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.RESTRICTED,
        chunk_texts=["Admin-visible restricted content about server infrastructure costs."],
    )

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    token = await _login(client, admin_email, admin_password)

    response = await client.post(
        "/api/search",
        headers=_auth(token),
        json={
            "query": "Admin-visible restricted content about server infrastructure costs.",
            "similarity_threshold": 0.0,
        },
    )
    assert response.status_code == 200
    result_chunk_ids = {r["chunk_id"] for r in response.json()["results"]}
    assert str(chunks[0].id) in result_chunk_ids


# --- Filters ---


async def test_search_filters_by_file_type(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
        chunk_texts=["A distinctly worded passage about quarterly budget allocations."],
    )

    token = await _login(client, manager_email, manager_password)
    response = await client.post(
        "/api/search",
        headers=_auth(token),
        json={
            "query": "A distinctly worded passage about quarterly budget allocations.",
            "similarity_threshold": 0.0,
            "file_type": "pdf",  # document is txt, so this must exclude it
        },
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


# --- Direct service-level test of retrieval_service.search with an injected provider ---


async def test_retrieval_service_direct_injection(session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document, chunks = await _create_embedded_document(
        session,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
        chunk_texts=["Direct service call test phrase about vacation scheduling."],
    )

    results = await retrieval_service.search(
        session,
        manager,
        "Direct service call test phrase about vacation scheduling.",
        similarity_threshold=0.0,
        embedding_provider=_MOCK_PROVIDER,
    )
    assert len(results) >= 1
    assert results[0].chunk_id == chunks[0].id
    assert results[0].relevance_score == 1.0
