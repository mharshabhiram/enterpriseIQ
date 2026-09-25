"""
Tests for app.db.seed - the local-development seed script (project brief
section 30). Runs against the real database with real commits (the script
itself manages its own session/commits, same as it does when run via
`python -m app.db.seed`), and cleans up afterward.
"""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session_factory, engine
from app.main import app
from app.repositories import user_repository
from app.security.password import verify_password


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_pool():
    """Same rationale as tests/test_ingestion.py: this test uses the app's
    shared engine with real commits, not an isolated per-test engine, so the
    pool must be disposed before each test to avoid a pooled asyncpg
    connection from a previous test's (now-closed) event loop being reused."""
    await engine.dispose()
    yield


async def test_seeded_accounts_can_actually_log_in_via_http() -> None:
    """
    Deliberately goes through the real HTTP /api/auth/login endpoint rather
    than the repository directly - this is the test that would have caught
    a real bug found during Phase 10's manual end-to-end smoke test: the
    seed script originally used `.local` email addresses (e.g.
    admin@enterpriseiq.local), which `email-validator` (backing Pydantic's
    EmailStr on LoginRequest) correctly rejects as a special-use/reserved
    TLD per RFC 6762. Every other seed test - and every RBAC test in the
    whole suite - creates users directly via user_repository.create with
    @example.com addresses, bypassing EmailStr validation entirely, so none
    of them could have caught this. Fixed by switching to `.example`
    (RFC 2606's reserved documentation TLD, which validators do accept).
    """
    from app.db.seed import SEED_USERS, seed

    await seed()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for spec in SEED_USERS:
                response = await client.post(
                    "/api/auth/login", json={"email": spec["email"], "password": spec["password"]}
                )
                assert response.status_code == 200, (
                    f"seeded account {spec['email']} could not log in via the real HTTP "
                    f"endpoint: {response.status_code} {response.text}"
                )
                assert response.json()["user"]["role"] == spec["role"].value
    finally:
        async with async_session_factory() as session:
            for spec in SEED_USERS:
                user = await user_repository.get_by_email(session, spec["email"])
                if user is not None:
                    await user_repository.delete(session, user)
            await session.commit()


async def test_seed_creates_admin_manager_and_employee() -> None:
    from app.db.seed import SEED_USERS, seed

    await seed()

    async with async_session_factory() as session:
        try:
            for spec in SEED_USERS:
                user = await user_repository.get_by_email(session, spec["email"])
                assert user is not None, f"seed did not create {spec['email']}"
                assert user.role == spec["role"]
                assert user.is_active is True
                assert verify_password(spec["password"], user.password_hash)
        finally:
            # Clean up so this test doesn't leave permanent rows behind for
            # other tests/manual runs to trip over.
            for spec in SEED_USERS:
                user = await user_repository.get_by_email(session, spec["email"])
                if user is not None:
                    # Bypass user_service's "can't delete last admin" guard by
                    # deleting non-admins first, then the admin last (there's
                    # no other admin in a clean test DB, so use the repository
                    # directly rather than the guarded service for this cleanup).
                    from app.repositories import user_repository as repo

                    await repo.delete(session, user)
            await session.commit()


async def test_seed_is_idempotent() -> None:
    from app.db.seed import SEED_USERS, seed

    await seed()
    await seed()  # must not raise (e.g. duplicate email) or create duplicates

    async with async_session_factory() as session:
        try:
            for spec in SEED_USERS:
                # get_by_email returning exactly one user (not raising
                # MultipleResultsFound) proves no duplicate was created.
                user = await user_repository.get_by_email(session, spec["email"])
                assert user is not None
        finally:
            from app.repositories import user_repository as repo

            for spec in SEED_USERS:
                user = await user_repository.get_by_email(session, spec["email"])
                if user is not None:
                    await repo.delete(session, user)
            await session.commit()
