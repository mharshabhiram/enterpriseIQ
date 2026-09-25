"""
Rate limiting is disabled by default in the test environment (see
tests/conftest.py) so the rest of the suite - which logs in dozens of times
across all test files, all appearing to originate from the same address
under httpx's ASGITransport - doesn't spuriously trip the limiter. This
file is the one place that turns it on, verifies the real behavior, and
turns it back off (and resets counters) so it can't leak into other tests.
"""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import engine
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_pool():
    """Same rationale as tests/test_ingestion.py: these tests hit the app's
    real, default get_db (no session override), so the shared engine pool
    must be disposed before each test to avoid a pooled asyncpg connection
    from a previous test's (now-closed) event loop being reused."""
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def rate_limiting_enabled():
    limiter = app.state.limiter
    limiter.enabled = True
    limiter.reset()
    yield limiter
    limiter.reset()
    limiter.enabled = False


async def test_login_rate_limit_returns_429_after_threshold(client: AsyncClient, rate_limiting_enabled) -> None:
    # login is limited to 10/minute (see app/api/routes/auth.py); credentials
    # are wrong on purpose - the rate limit fires before auth logic even runs.
    payload = {"email": "nobody@example.com", "password": "wrong-password"}

    statuses = [(await client.post("/api/auth/login", json=payload)).status_code for _ in range(10)]
    assert all(s == 401 for s in statuses)  # all 10 allowed through (wrong creds, but not rate-limited)

    limited_response = await client.post("/api/auth/login", json=payload)
    assert limited_response.status_code == 429
    assert limited_response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


async def test_register_rate_limit_returns_429_after_threshold(client: AsyncClient, rate_limiting_enabled) -> None:
    import uuid

    # register is limited to 5/minute (see app/api/routes/auth.py).
    for _ in range(5):
        response = await client.post(
            "/api/auth/register",
            json={"name": "X", "email": f"{uuid.uuid4()}@example.com", "password": "StrongPassw0rd!"},
        )
        assert response.status_code == 201, response.text

    limited_response = await client.post(
        "/api/auth/register",
        json={"name": "X", "email": f"{uuid.uuid4()}@example.com", "password": "StrongPassw0rd!"},
    )
    assert limited_response.status_code == 429
    assert limited_response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
