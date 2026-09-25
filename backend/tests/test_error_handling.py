"""
Tests the catch-all exception handler in app.main: a genuinely unexpected
bug (not a deliberately-raised AppError) must still come back as our
consistent {"error": {...}} envelope with a 500, never a raw crash or a
differently-shaped response - and must never leak exception internals to
the client when DEBUG is off.
"""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client():
    # raise_app_exceptions=False: let the app's own registered Exception
    # handler process an unhandled bug (as it would in a real deployment)
    # instead of httpx re-raising it straight into the test - which is
    # ASGITransport's default, specifically so *other* tests fail loudly on
    # unexpected bugs rather than silently getting a 500. Here, testing that
    # very handler is the point.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_unhandled_exception_returns_consistent_error_envelope(client: AsyncClient, monkeypatch) -> None:
    async def _boom(*args, **kwargs):
        raise RuntimeError("a genuinely unexpected bug, not a deliberate AppError")

    # user_repository.get_by_email is called early in the login flow.
    monkeypatch.setattr("app.services.auth_service.user_repository.get_by_email", _boom)
    # Settings.debug defaults to True (a local-dev-friendly default - see
    # app/config.py), so this must be made explicit rather than assumed.
    monkeypatch.setattr("app.main.settings.debug", False)

    response = await client.post(
        "/api/auth/login", json={"email": "someone@example.com", "password": "whatever123"}
    )
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    # Never leak exception internals to the client when DEBUG is off.
    assert "a genuinely unexpected bug" not in response.text


async def test_unhandled_exception_includes_details_when_debug_enabled(
    client: AsyncClient, monkeypatch
) -> None:
    async def _boom(*args, **kwargs):
        raise RuntimeError("debug-visible detail")

    monkeypatch.setattr("app.services.auth_service.user_repository.get_by_email", _boom)
    monkeypatch.setattr("app.main.settings.debug", True)

    response = await client.post(
        "/api/auth/login", json={"email": "someone@example.com", "password": "whatever123"}
    )
    assert response.status_code == 500
    assert "debug-visible detail" in response.json()["error"]["message"]
