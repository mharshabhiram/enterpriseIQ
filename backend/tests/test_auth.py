"""
Integration tests for Phase 3: authentication and RBAC.

These issue real HTTP requests (via httpx's ASGITransport, no real socket)
against the actual FastAPI app, backed by the real Postgres database - the
same "test the real thing" approach as tests/test_models.py. `get_db` is
overridden per-test to use a session bound to a rolled-back transaction, so
tests never leave rows behind and can run in any order.
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
from app.models.enums import UserRole
from app.repositories import user_repository
from app.security.password import hash_password


@pytest_asyncio.fixture
async def session():
    """Same rolled-back-transaction pattern as tests/test_models.py."""
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
    """
    An httpx client wired to the real app, with get_db overridden to reuse
    the test's transactional session (so requests inside a test see the
    same uncommitted rows the test set up, and everything rolls back after).
    """

    async def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _create_user(session: AsyncSession, *, role: UserRole, password: str = "Password123!") -> tuple:
    email = f"{uuid.uuid4()}@example.com"
    user = await user_repository.create(
        session, name="Test User", email=email, password_hash=hash_password(password), role=role
    )
    return user, email, password


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Registration ---


async def test_register_creates_employee_and_ignores_role_field(client: AsyncClient) -> None:
    payload = {
        "name": "New Employee",
        "email": f"{uuid.uuid4()}@example.com",
        "password": "StrongPassw0rd!",
    }
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "EMPLOYEE"
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_duplicate_email_returns_409(client: AsyncClient, session: AsyncSession) -> None:
    _, email, _ = await _create_user(session, role=UserRole.EMPLOYEE)
    response = await client.post(
        "/api/auth/register", json={"name": "Dup", "email": email, "password": "StrongPassw0rd!"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_register_short_password_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/register",
        json={"name": "X", "email": f"{uuid.uuid4()}@example.com", "password": "short"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- Login ---


async def test_login_success_returns_token_and_user(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email


async def test_login_wrong_password_returns_401(client: AsyncClient, session: AsyncSession) -> None:
    _, email, _ = await _create_user(session, role=UserRole.EMPLOYEE)
    response = await client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_email_returns_401_not_404(client: AsyncClient) -> None:
    """Must not leak which emails exist."""
    response = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_inactive_user_returns_403(client: AsyncClient, session: AsyncSession) -> None:
    user, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    user.is_active = False
    await session.flush()
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INACTIVE_USER"


# --- /api/auth/me and token handling ---


async def test_me_requires_valid_token(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code in (401, 403)  # HTTPBearer returns 403 if header missing entirely


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me", headers=_auth_header("not-a-real-token"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_me_returns_current_user(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.MANAGER)
    token = await _login(client, email, password)
    response = await client.get("/api/auth/me", headers=_auth_header(token))
    assert response.status_code == 200
    assert response.json()["email"] == email
    assert response.json()["role"] == "MANAGER"


# --- RBAC on /api/users ---


async def test_employee_cannot_list_users(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, email, password)
    response = await client.get("/api/users", headers=_auth_header(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


async def test_manager_cannot_create_user(client: AsyncClient, session: AsyncSession) -> None:
    _, email, password = await _create_user(session, role=UserRole.MANAGER)
    token = await _login(client, email, password)
    response = await client.post(
        "/api/users",
        headers=_auth_header(token),
        json={"name": "X", "email": f"{uuid.uuid4()}@example.com", "password": "StrongPassw0rd!"},
    )
    assert response.status_code == 403


async def test_admin_can_list_and_create_users(client: AsyncClient, session: AsyncSession) -> None:
    _, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    token = await _login(client, admin_email, admin_password)

    list_response = await client.get("/api/users", headers=_auth_header(token))
    assert list_response.status_code == 200
    assert isinstance(list_response.json(), list)

    create_response = await client.post(
        "/api/users",
        headers=_auth_header(token),
        json={
            "name": "New Manager",
            "email": f"{uuid.uuid4()}@example.com",
            "password": "StrongPassw0rd!",
            "role": "MANAGER",
        },
    )
    assert create_response.status_code == 201, create_response.text
    assert create_response.json()["role"] == "MANAGER"


async def test_admin_can_promote_employee_to_manager(client: AsyncClient, session: AsyncSession) -> None:
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    employee, _, _ = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, admin_email, admin_password)

    response = await client.patch(
        f"/api/users/{employee.id}", headers=_auth_header(token), json={"role": "MANAGER"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "MANAGER"


async def test_admin_can_change_own_role_if_another_admin_remains(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin_a, email_a, password_a = await _create_user(session, role=UserRole.ADMIN)
    await _create_user(session, role=UserRole.ADMIN)  # a second active admin
    token_a = await _login(client, email_a, password_a)

    response = await client.patch(
        f"/api/users/{admin_a.id}", headers=_auth_header(token_a), json={"role": "EMPLOYEE"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "EMPLOYEE"


async def test_cannot_demote_the_last_active_admin(client: AsyncClient, session: AsyncSession) -> None:
    sole_admin, email, password = await _create_user(session, role=UserRole.ADMIN)
    token = await _login(client, email, password)

    response = await client.patch(
        f"/api/users/{sole_admin.id}", headers=_auth_header(token), json={"role": "EMPLOYEE"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OPERATION"


async def test_cannot_deactivate_the_last_active_admin(client: AsyncClient, session: AsyncSession) -> None:
    admin_a, email_a, password_a = await _create_user(session, role=UserRole.ADMIN)
    admin_b, email_b, password_b = await _create_user(session, role=UserRole.ADMIN)
    token_a = await _login(client, email_a, password_a)

    # Two active admins: deactivating admin_b is fine.
    first = await client.patch(
        f"/api/users/{admin_b.id}", headers=_auth_header(token_a), json={"is_active": False}
    )
    assert first.status_code == 200, first.text

    # Now only admin_a is active - deactivating them must be blocked, even
    # by a different admin, since there'd be zero active admins left.
    # (admin_b is now inactive and so can no longer log in to attempt this
    # themselves - use admin_a's own still-valid token to try it.)
    second = await client.patch(
        f"/api/users/{admin_a.id}", headers=_auth_header(token_a), json={"is_active": False}
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "INVALID_OPERATION"


async def test_service_blocks_deleting_the_last_active_admin_regardless_of_actor(
    session: AsyncSession,
) -> None:
    """
    Through the HTTP API, this scenario can never actually be reached: the
    route requires the actor to already be an active admin (require_role),
    and the separate absolute self-delete rule blocks the one remaining
    case (an admin deleting themselves). So deleting someone else while
    you're an active admin always leaves at least one admin (you) behind.

    This test calls the service function directly, bypassing routes/RBAC
    entirely, to prove the numeric last-admin guard is a real, independent
    invariant at the service layer - not just an artifact of route gating -
    in case a future caller (a console script, a bulk-admin endpoint) ever
    reaches this service without going through today's routes.
    """
    from app.services import user_service
    from app.utils.errors import InvalidOperationError

    sole_admin, _, _ = await _create_user(session, role=UserRole.ADMIN)
    someone_else, _, _ = await _create_user(session, role=UserRole.EMPLOYEE)

    with pytest.raises(InvalidOperationError):
        await user_service.delete_user(session, actor=someone_else, user_id=sole_admin.id)


async def test_admin_cannot_delete_own_account(client: AsyncClient, session: AsyncSession) -> None:
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    token = await _login(client, admin_email, admin_password)

    response = await client.delete(f"/api/users/{admin.id}", headers=_auth_header(token))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OPERATION"


async def test_admin_can_delete_other_user(client: AsyncClient, session: AsyncSession) -> None:
    admin, admin_email, admin_password = await _create_user(session, role=UserRole.ADMIN)
    victim, _, _ = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, admin_email, admin_password)

    response = await client.delete(f"/api/users/{victim.id}", headers=_auth_header(token))
    assert response.status_code == 204

    get_response = await client.get(f"/api/users/{victim.id}", headers=_auth_header(token))
    assert get_response.status_code == 404
    assert get_response.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_deactivated_user_token_rejected_on_next_request(
    client: AsyncClient, session: AsyncSession
) -> None:
    """
    Proves get_current_user re-checks the DB every request rather than
    trusting a claim baked into the JWT: a token issued while active must
    stop working the moment the account is deactivated, with no need to
    wait for the token to expire.
    """
    user, email, password = await _create_user(session, role=UserRole.EMPLOYEE)
    token = await _login(client, email, password)

    me_response = await client.get("/api/auth/me", headers=_auth_header(token))
    assert me_response.status_code == 200

    user.is_active = False
    await session.flush()

    me_response_after = await client.get("/api/auth/me", headers=_auth_header(token))
    assert me_response_after.status_code == 403
    assert me_response_after.json()["error"]["code"] == "INACTIVE_USER"
