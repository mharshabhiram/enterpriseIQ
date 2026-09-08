"""
Phase 1 smoke test: confirms the FastAPI app boots and routers are wired
correctly. Real authentication/RBAC/RAG tests are added alongside their
respective phases (see section 27 of the project brief).
"""
from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "enterpriseiq-backend"
