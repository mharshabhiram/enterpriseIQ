import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/enterpriseiq_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["SIMILARITY_THRESHOLD"] = "0.1"
os.environ.setdefault("UPLOAD_DIR", "/tmp/enterpriseiq-test-uploads")
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"  # never reach a real Ollama in tests
os.environ["OLLAMA_STARTUP_WAIT_SECONDS"] = "0"

import pytest  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from tests.fakes import FakeEmbedder, FakeLLM  # noqa: E402

PASSWORD = "Test-Password-123"
HERE = os.path.dirname(__file__)


def _db_available() -> bool:
    try:
        with create_engine(os.environ["TEST_DATABASE_URL"]).connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


@pytest.fixture(scope="session")
def migrated_db():
    if not _db_available():
        pytest.skip("TEST_DATABASE_URL is not reachable; integration tests skipped")
    from alembic import command
    from alembic.config import Config

    with create_engine(os.environ["TEST_DATABASE_URL"]).begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(HERE, "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def fakes():
    return FakeLLM(), FakeEmbedder()


@pytest.fixture(scope="session")
def client(migrated_db, fakes):
    from fastapi.testclient import TestClient

    import app.services.ingestion_service as ingestion
    from app.api import dependencies
    from app.main import app
    from app.security.rate_limit import limiter

    llm, embedder = fakes
    limiter.enabled = False
    app.dependency_overrides[dependencies.llm_provider] = lambda: llm
    app.dependency_overrides[dependencies.embedding_provider] = lambda: embedder
    ingestion.get_embedding_provider = lambda: embedder
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def users(client):
    """One user per role (plus a second manager/employee); returns {key: {"id", "headers"}}."""
    from app.database import SessionLocal
    from app.models import Role, User
    from app.security.passwords import hash_password

    spec = {
        "ADMIN": "admin@test.enterpriseiq.dev",
        "MANAGER": "manager@test.enterpriseiq.dev",
        "MANAGER2": "manager2@test.enterpriseiq.dev",
        "EMPLOYEE": "employee@test.enterpriseiq.dev",
        "EMPLOYEE2": "employee2@test.enterpriseiq.dev",
    }
    with SessionLocal() as db:
        roles = {r.name: r.id for r in db.scalars(select(Role))}
        for key, email in spec.items():
            db.add(User(name=key.title(), email=email, password_hash=hash_password(PASSWORD), role_id=roles[key.rstrip("2")]))
        db.commit()
    out = {}
    for key, email in spec.items():
        token = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        out[key] = {"headers": headers, "id": client.get("/api/auth/me", headers=headers).json()["id"]}
    return out
