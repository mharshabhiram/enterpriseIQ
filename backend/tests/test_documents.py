"""
Integration tests for Phase 4 document RBAC and CRUD (list, get, delete,
permissions). Documents are created directly via document_repository within
the test's own transaction, rather than through the upload endpoint - this
sidesteps the background-processing task entirely (which opens its own
session against the *real* engine and can't see this transaction's
uncommitted rows; see tests/test_ingestion.py for tests that exercise the
actual upload + background pipeline against real commits).
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_db
from app.config import settings
from app.main import app
from app.models.enums import DocumentVisibility, GranteeType, UserRole
from app.models.document_permission import DocumentPermission
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


async def _create_document(session, *, uploaded_by, visibility=DocumentVisibility.RESTRICTED, file_type="pdf"):
    return await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.{file_type}",
        original_filename=f"doc.{file_type}",
        file_type=file_type,
        file_size=1234,
        uploaded_by=uploaded_by,
        visibility=visibility,
    )


# --- Upload RBAC (role gate only; actual pipeline tested in test_ingestion.py) ---


async def test_employee_cannot_upload(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, email, password)
    response = await client.post(
        "/api/documents",
        headers=_auth(token),
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


# --- Listing / visibility ---


async def test_list_documents_respects_visibility(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    employee, employee_email, employee_password = await _create_user(session, role=UserRole.EMPLOYEE)

    await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.PUBLIC)
    await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    token = await _login(client, employee_email, employee_password)
    response = await client.get("/api/documents", headers=_auth(token))
    assert response.status_code == 200
    assert len(response.json()) == 1  # only the PUBLIC one


async def test_admin_sees_all_documents(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)

    await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.PUBLIC)
    await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    token = await _login(client, admin_email, admin_password)
    response = await client.get("/api/documents", headers=_auth(token))
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_restricted_document_without_access_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    other, other_email, other_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, other_email, other_password)

    response = await client.get(f"/api/documents/{document.id}", headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_owner_can_see_own_restricted_document(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    token = await _login(client, manager_email, manager_password)
    response = await client.get(f"/api/documents/{document.id}", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["id"] == str(document.id)


async def test_role_grant_makes_restricted_document_visible(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    employee, employee_email, employee_password = await _create_user(session, role=UserRole.EMPLOYEE)
    session.add(DocumentPermission(document_id=document.id, grantee_type=GranteeType.ROLE, role=UserRole.EMPLOYEE))
    await session.flush()

    token = await _login(client, employee_email, employee_password)
    response = await client.get(f"/api/documents/{document.id}", headers=_auth(token))
    assert response.status_code == 200


# --- Deletion RBAC ---


async def test_manager_can_delete_own_document(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id)

    token = await _login(client, manager_email, manager_password)
    response = await client.delete(f"/api/documents/{document.id}", headers=_auth(token))
    assert response.status_code == 204


async def test_manager_cannot_delete_others_document(client: AsyncClient, session: AsyncSession) -> None:
    manager_a, _, _ = await _create_user(session, role=UserRole.MANAGER)
    manager_b, manager_b_email, manager_b_password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager_a.id, visibility=DocumentVisibility.PUBLIC)

    token = await _login(client, manager_b_email, manager_b_password)
    response = await client.delete(f"/api/documents/{document.id}", headers=_auth(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


async def test_admin_can_delete_any_document(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    document = await _create_document(session, uploaded_by=manager.id)

    token = await _login(client, admin_email, admin_password)
    response = await client.delete(f"/api/documents/{document.id}", headers=_auth(token))
    assert response.status_code == 204


async def test_employee_cannot_delete_document(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.PUBLIC)

    employee, employee_email, employee_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, employee_email, employee_password)
    response = await client.delete(f"/api/documents/{document.id}", headers=_auth(token))
    assert response.status_code == 403


# --- Visibility updates ---


async def test_manager_can_change_own_document_visibility(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    token = await _login(client, manager_email, manager_password)
    response = await client.patch(
        f"/api/documents/{document.id}", headers=_auth(token), json={"visibility": "PUBLIC"}
    )
    assert response.status_code == 200
    assert response.json()["visibility"] == "PUBLIC"


# --- Permissions (ADMIN-only) ---


async def test_manager_cannot_manage_permissions(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id)

    token = await _login(client, manager_email, manager_password)
    response = await client.post(
        f"/api/documents/{document.id}/permissions",
        headers=_auth(token),
        json={"grantee_type": "ROLE", "role": "EMPLOYEE"},
    )
    assert response.status_code == 403


async def test_admin_can_grant_and_revoke_permission(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    token = await _login(client, admin_email, admin_password)
    grant_response = await client.post(
        f"/api/documents/{document.id}/permissions",
        headers=_auth(token),
        json={"grantee_type": "ROLE", "role": "EMPLOYEE"},
    )
    assert grant_response.status_code == 201, grant_response.text
    permission_id = grant_response.json()["id"]

    list_response = await client.get(f"/api/documents/{document.id}/permissions", headers=_auth(token))
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    revoke_response = await client.delete(
        f"/api/documents/{document.id}/permissions/{permission_id}", headers=_auth(token)
    )
    assert revoke_response.status_code == 204

    list_after = await client.get(f"/api/documents/{document.id}/permissions", headers=_auth(token))
    assert list_after.json() == []


async def test_permission_grant_rejects_malformed_role_grant(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    document = await _create_document(session, uploaded_by=manager.id)

    token = await _login(client, admin_email, admin_password)
    # ROLE grant with a user_id set too - invalid shape, must be rejected before hitting the DB.
    response = await client.post(
        f"/api/documents/{document.id}/permissions",
        headers=_auth(token),
        json={"grantee_type": "ROLE", "role": "EMPLOYEE", "user_id": str(uuid.uuid4())},
    )
    assert response.status_code == 422


# --- Download (previously untested - found via coverage review) ---


async def test_download_document_returns_file_content(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.PUBLIC)

    # The repository row references a stored filename that doesn't actually
    # exist on disk in this test (no real upload happened) - write a real
    # file there so the download endpoint has something real to stream back.
    import os

    from app.config import settings as app_settings

    os.makedirs(app_settings.upload_dir, exist_ok=True)
    file_path = os.path.join(app_settings.upload_dir, document.filename)
    with open(file_path, "wb") as f:
        f.write(b"fake pdf content for download test")

    token = await _login(client, manager_email, manager_password)
    try:
        response = await client.get(f"/api/documents/{document.id}/download", headers=_auth(token))
        assert response.status_code == 200
        assert response.content == b"fake pdf content for download test"
        assert "doc.pdf" in response.headers.get("content-disposition", "")
    finally:
        os.remove(file_path)


async def test_download_restricted_document_without_access_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    document = await _create_document(session, uploaded_by=manager.id, visibility=DocumentVisibility.RESTRICTED)

    outsider, outsider_email, outsider_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, outsider_email, outsider_password)

    response = await client.get(f"/api/documents/{document.id}/download", headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
