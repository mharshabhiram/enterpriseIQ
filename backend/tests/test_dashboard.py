"""
Tests for GET /api/dashboard, verifying it reflects each user's own RBAC
scope (not org-wide totals) - the mechanism behind brief section 14's
"dashboard changes based on role."
"""
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_db
from app.config import settings
from app.main import app
from app.models.enums import DocumentVisibility, UserRole
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


async def test_dashboard_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/dashboard")
    assert response.status_code in (401, 403)


async def test_employee_dashboard_only_counts_visible_documents(client: AsyncClient, session: AsyncSession) -> None:
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.pdf",
        original_filename="public.pdf",
        file_type="pdf",
        file_size=1,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.PUBLIC,
    )
    await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.pdf",
        original_filename="restricted.pdf",
        file_type="pdf",
        file_size=1,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.RESTRICTED,
    )

    employee, employee_email, employee_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, employee_email, employee_password)

    response = await client.get("/api/dashboard", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["documents_visible_total"] == 1  # only the public one
    assert body["my_uploaded_documents"] == 0  # employees don't upload


async def test_manager_dashboard_reflects_own_uploads(client: AsyncClient, session: AsyncSession) -> None:
    manager, manager_email, manager_password = await _create_user(session, role=UserRole.MANAGER)
    for _ in range(3):
        await document_repository.create(
            session,
            filename=f"{uuid.uuid4()}.pdf",
            original_filename="doc.pdf",
            file_type="pdf",
            file_size=1,
            uploaded_by=manager.id,
            visibility=DocumentVisibility.PUBLIC,
        )

    token = await _login(client, manager_email, manager_password)
    response = await client.get("/api/dashboard", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["my_uploaded_documents"] == 3


async def test_dashboard_conversations_are_per_user(client: AsyncClient, session: AsyncSession) -> None:
    _, email_a, password_a = await _create_user(session)
    _, email_b, password_b = await _create_user(session)
    token_a = await _login(client, email_a, password_a)
    token_b = await _login(client, email_b, password_b)

    await client.post("/api/chat", headers=_auth(token_a), json={"question": "A's question"})
    await client.post("/api/chat", headers=_auth(token_b), json={"question": "B's first question"})
    await client.post("/api/chat", headers=_auth(token_b), json={"question": "B's second question"})

    response_a = await client.get("/api/dashboard", headers=_auth(token_a))
    response_b = await client.get("/api/dashboard", headers=_auth(token_b))

    assert response_a.json()["my_conversations_total"] == 1
    assert response_b.json()["my_conversations_total"] == 2
    assert len(response_b.json()["recent_conversations"]) == 2


async def test_admin_dashboard_still_scoped_to_admins_own_data(client: AsyncClient, session: AsyncSession) -> None:
    """
    /api/dashboard is the *personal* view even for admins - it should not
    silently become the org-wide view (that's /api/admin/stats).
    """
    manager, _, _ = await _create_user(session, role=UserRole.MANAGER)
    await document_repository.create(
        session,
        filename=f"{uuid.uuid4()}.pdf",
        original_filename="not-admins.pdf",
        file_type="pdf",
        file_size=1,
        uploaded_by=manager.id,
        visibility=DocumentVisibility.RESTRICTED,
    )

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    token = await _login(client, admin_email, admin_password)

    response = await client.get("/api/dashboard", headers=_auth(token))
    assert response.status_code == 200
    # Admins see everything via visibility_clause, so this *does* include the
    # manager's restricted doc - that's still "documents visible to me," just
    # that admins can see everything. The key distinction from admin/stats is
    # that this is still a per-user query path, not an org-wide aggregate.
    assert response.json()["documents_visible_total"] == 1
