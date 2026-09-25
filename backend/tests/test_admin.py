"""
Tests for the admin-only stats and audit log endpoints: RBAC gating,
org-wide (not per-user) aggregation, and audit log filtering.
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


# --- RBAC ---


async def test_stats_requires_admin(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.MANAGER)
    token = await _login(client, email, password)

    response = await client.get("/api/admin/stats", headers=_auth(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


async def test_audit_logs_requires_admin(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, email, password)

    response = await client.get("/api/admin/audit-logs", headers=_auth(token))
    assert response.status_code == 403


# --- Stats content: org-wide, not per-user ---


async def test_admin_stats_counts_all_documents_regardless_of_visibility(
    client: AsyncClient, session: AsyncSession
) -> None:
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

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    token = await _login(client, admin_email, admin_password)

    response = await client.get("/api/admin/stats", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_documents"] == 2  # both, regardless of who could "see" them
    assert body["total_users"] == 2  # manager + admin
    assert "MANAGER" in body["users_by_role"]
    assert "ADMIN" in body["users_by_role"]


async def test_admin_stats_includes_recent_uploads_and_conversations(
    client: AsyncClient, session: AsyncSession
) -> None:
    employee, employee_email, employee_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, employee_email, employee_password)
    await client.post("/api/chat", headers=_auth(token), json={"question": "A question"})

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    admin_token = await _login(client, admin_email, admin_password)

    response = await client.get("/api/admin/stats", headers=_auth(admin_token))
    assert response.status_code == 200
    body = response.json()
    assert body["total_conversations"] == 1
    assert len(body["recent_activity"]) >= 1


async def test_admin_stats_most_searched_queries_counts_frequency(
    client: AsyncClient, session: AsyncSession
) -> None:
    employee, employee_email, employee_password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, employee_email, employee_password)

    for _ in range(3):
        await client.post("/api/search", headers=_auth(token), json={"query": "what is the leave policy"})
    await client.post("/api/search", headers=_auth(token), json={"query": "a totally different question"})

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    admin_token = await _login(client, admin_email, admin_password)

    response = await client.get("/api/admin/stats", headers=_auth(admin_token))
    assert response.status_code == 200
    top_queries = {item["query"]: item["count"] for item in response.json()["most_searched_queries"]}
    assert top_queries["what is the leave policy"] == 3
    assert top_queries["a totally different question"] == 1


# --- Audit log listing and filtering ---


async def test_admin_can_list_audit_logs(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, email, password)
    await client.post("/api/chat", headers=_auth(token), json={"question": "hi"})

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    admin_token = await _login(client, admin_email, admin_password)

    response = await client.get("/api/admin/audit-logs", headers=_auth(admin_token))
    assert response.status_code == 200
    actions = {entry["action"] for entry in response.json()}
    assert "USER_LOGIN" in actions
    assert "CHAT_REQUEST" in actions


async def test_audit_logs_filter_by_action(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, email, password)
    await client.post("/api/chat", headers=_auth(token), json={"question": "hi"})

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    admin_token = await _login(client, admin_email, admin_password)

    response = await client.get(
        "/api/admin/audit-logs", headers=_auth(admin_token), params={"action": "CHAT_REQUEST"}
    )
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) >= 1
    assert all(entry["action"] == "CHAT_REQUEST" for entry in entries)


async def test_audit_logs_filter_by_user_id(client: AsyncClient, session: AsyncSession) -> None:
    user_a, email_a, password_a = await _create_user(session, role=UserRole.EMPLOYEE)
    user_b, email_b, password_b = await _create_user(session, role=UserRole.EMPLOYEE)
    token_a = await _login(client, email_a, password_a)
    token_b = await _login(client, email_b, password_b)
    await client.post("/api/chat", headers=_auth(token_a), json={"question": "from a"})
    await client.post("/api/chat", headers=_auth(token_b), json={"question": "from b"})

    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    admin_token = await _login(client, admin_email, admin_password)

    response = await client.get(
        "/api/admin/audit-logs",
        headers=_auth(admin_token),
        params={"user_id": str(user_a.id), "action": "CHAT_REQUEST"},
    )
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["user_id"] == str(user_a.id)
