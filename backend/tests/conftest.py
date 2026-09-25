"""
Shared pytest configuration.

Sets sane defaults for environment variables the test suite needs *before*
app.config is ever imported (Settings are loaded once, at import time, via
an lru_cache) - these are only defaults (setdefault), so a real environment
or CI runner that already sets these takes precedence.

EMBEDDING_PROVIDER defaults to 'mock' here specifically so the full
ingestion/search pipeline can be exercised end-to-end (including through
the real HTTP upload endpoint and its background task) without requiring
network access or a real API key - see app/ai/mock_embedding_provider.py.
LLM_PROVIDER defaults to 'mock' for the same reason, for the /api/chat
pipeline - see app/ai/mock_llm_provider.py.
"""
import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://enterpriseiq:enterpriseiq@localhost:5432/enterpriseiq"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-do-not-use-in-production")
os.environ.setdefault("UPLOAD_DIR", "/tmp/enterpriseiq-uploads")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
