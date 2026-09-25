"""
End-to-end tests for the Phase 4 ingestion pipeline: real file uploads
through the actual HTTP endpoint, with the real FastAPI BackgroundTasks
mechanism actually running app.services.ingestion_service.process_document.

These deliberately do NOT use the rolled-back-transaction pattern from
tests/test_documents.py: process_document opens its own session against the
real app engine (app.db.session.async_session_factory), which is a
different connection than any per-test transaction and can't see
uncommitted rows in it. So these tests run against real commits and clean
up everything they create in a `finally` block instead.

Confirmed empirically while writing these tests: httpx's ASGITransport
drives a request all the way through Starlette's response-sending, which
includes running BackgroundTasks, before `await client.post(...)` returns -
so there's no need to sleep/poll for processing to finish.
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory, engine
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.enums import ProcessingStatus, UserRole
from app.repositories import user_repository
from app.security.password import hash_password


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_pool():
    """
    The background task (ingestion_service.process_document) uses the app's
    module-level singleton engine/session-factory - not the isolated
    per-test engine pattern used in test_documents.py/test_models.py.
    pytest-asyncio gives each test function a fresh event loop by default,
    but the singleton engine's connection pool persists across tests, so a
    pooled asyncpg connection from a previous test's (now-closed) loop would
    get reused and raise "attached to a different loop." Disposing the pool
    before each test forces fresh connections bound to the current loop.
    """
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def real_session():
    """A real, committing session against the actual app database - no rollback."""
    async with async_session_factory() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_committed_user(session: AsyncSession, *, role: UserRole, password: str = "Password123!"):
    email = f"{uuid.uuid4()}@example.com"
    user = await user_repository.create(
        session, name="Ingestion Test User", email=email, password_hash=hash_password(password), role=role
    )
    await session.commit()
    return user, email, password


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _cleanup_document(document_id: uuid.UUID) -> None:
    """Deletes the document (cascades to chunks) - best-effort test cleanup."""
    async with async_session_factory() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            await session.delete(document)
            await session.commit()


async def test_pdf_upload_is_extracted_and_chunked(client: AsyncClient, real_session: AsyncSession) -> None:
    manager, email, password = await _create_committed_user(real_session, role=UserRole.MANAGER)
    token = await _login(client, email, password)

    with open("/tmp/sample_files/handbook.pdf", "rb") as f:
        pdf_bytes = f.read()

    document_id = None
    try:
        response = await client.post(
            "/api/documents",
            headers=_auth(token),
            files={"file": ("handbook.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        document_id = uuid.UUID(body["id"])

        # By now the background task has already run (see module docstring).
        async with async_session_factory() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            assert document.processing_status == ProcessingStatus.COMPLETED, document.processing_error
            assert document.page_count == 2
            assert document.chunk_count >= 2

            chunks_result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            chunks = chunks_result.scalars().all()
            assert len(chunks) == document.chunk_count
            page_numbers = {chunk.page_number for chunk in chunks}
            assert page_numbers == {1, 2}
            # Phase 5: embeddings are now generated as part of this same
            # pipeline (via EMBEDDING_PROVIDER=mock in the test environment -
            # see tests/conftest.py). Phase 4 originally asserted these were
            # NULL; that was true only before Phase 5 extended the pipeline.
            assert all(chunk.embedding is not None for chunk in chunks)
            assert all(len(chunk.embedding) == 1536 for chunk in chunks)
    finally:
        if document_id is not None:
            await _cleanup_document(document_id)


async def test_docx_upload_captures_section_titles(client: AsyncClient, real_session: AsyncSession) -> None:
    manager, email, password = await _create_committed_user(real_session, role=UserRole.MANAGER)
    token = await _login(client, email, password)

    with open("/tmp/sample_files/policy.docx", "rb") as f:
        docx_bytes = f.read()

    document_id = None
    try:
        response = await client.post(
            "/api/documents",
            headers=_auth(token),
            files={
                "file": (
                    "policy.docx",
                    docx_bytes,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 201, response.text
        document_id = uuid.UUID(response.json()["id"])

        async with async_session_factory() as session:
            document = await session.get(Document, document_id)
            assert document.processing_status == ProcessingStatus.COMPLETED, document.processing_error
            assert document.page_count is None  # DOCX has no page concept in this pipeline

            chunks_result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            chunks = chunks_result.scalars().all()
            section_titles = {chunk.section_title for chunk in chunks}
            assert "Introduction" in section_titles
            assert "Leave Policy" in section_titles
    finally:
        if document_id is not None:
            await _cleanup_document(document_id)


async def test_txt_and_md_uploads_are_processed(client: AsyncClient, real_session: AsyncSession) -> None:
    manager, email, password = await _create_committed_user(real_session, role=UserRole.MANAGER)
    token = await _login(client, email, password)

    document_ids = []
    try:
        for path, filename, mime in [
            ("/tmp/sample_files/notes.txt", "notes.txt", "text/plain"),
            ("/tmp/sample_files/readme.md", "readme.md", "text/markdown"),
        ]:
            with open(path, "rb") as f:
                content = f.read()
            response = await client.post(
                "/api/documents", headers=_auth(token), files={"file": (filename, content, mime)}
            )
            assert response.status_code == 201, response.text
            doc_id = uuid.UUID(response.json()["id"])
            document_ids.append(doc_id)

            async with async_session_factory() as session:
                document = await session.get(Document, doc_id)
                assert document.processing_status == ProcessingStatus.COMPLETED, document.processing_error
                assert document.chunk_count >= 1
    finally:
        for doc_id in document_ids:
            await _cleanup_document(doc_id)


async def test_unsupported_file_type_rejected_before_processing(
    client: AsyncClient, real_session: AsyncSession
) -> None:
    manager, email, password = await _create_committed_user(real_session, role=UserRole.MANAGER)
    token = await _login(client, email, password)

    response = await client.post(
        "/api/documents",
        headers=_auth(token),
        files={"file": ("malware.exe", b"MZ\x90\x00fake-exe-content", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_mislabeled_file_content_rejected(client: AsyncClient, real_session: AsyncSession) -> None:
    """A .pdf extension on non-PDF bytes must fail content validation, not silently process."""
    manager, email, password = await _create_committed_user(real_session, role=UserRole.MANAGER)
    token = await _login(client, email, password)

    response = await client.post(
        "/api/documents",
        headers=_auth(token),
        files={"file": ("fake.pdf", b"this is not a pdf at all", "application/pdf")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FILE_VALIDATION_ERROR"


async def test_empty_txt_file_marks_document_failed(client: AsyncClient, real_session: AsyncSession) -> None:
    """Validation passes (it's valid UTF-8 text) but there's nothing to extract, so ingestion marks FAILED."""
    manager, email, password = await _create_committed_user(real_session, role=UserRole.MANAGER)
    token = await _login(client, email, password)

    document_id = None
    try:
        response = await client.post(
            "/api/documents",
            headers=_auth(token),
            files={"file": ("empty.txt", b"   \n\n   ", "text/plain")},
        )
        assert response.status_code == 201, response.text
        document_id = uuid.UUID(response.json()["id"])

        async with async_session_factory() as session:
            document = await session.get(Document, document_id)
            assert document.processing_status == ProcessingStatus.FAILED
            assert document.processing_error is not None
            assert document.chunk_count == 0
    finally:
        if document_id is not None:
            await _cleanup_document(document_id)
