"""
Central application configuration.

All environment-specific values live here and are loaded from environment
variables (see .env.example). Nothing in the rest of the codebase should
read os.environ directly - always go through `settings`.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_env: str = "development"
    debug: bool = True

    # --- Database ---
    database_url: str = "postgresql+asyncpg://enterpriseiq:enterpriseiq@postgres:5432/enterpriseiq"

    # --- JWT / Auth ---
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # --- LLM (provider-agnostic; see app/ai) ---
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: Optional[str] = None

    # --- Embeddings ---
    embedding_provider: str = "openai"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_base_url: Optional[str] = None

    # --- RAG / retrieval tuning (never hard-code these elsewhere) ---
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 5
    similarity_threshold: float = 0.75
    max_context_length: int = 6000

    # --- Uploads ---
    max_file_size: int = 25 * 1024 * 1024  # 25 MB
    upload_dir: str = "/app/uploads"
    allowed_file_types: List[str] = ["pdf", "docx", "txt", "md"]

    # --- CORS ---
    cors_origins: List[str] = ["http://localhost:5173"]

    # --- Rate limiting ---
    # Disabled by default in the test environment (see tests/conftest.py) so
    # the full test suite - which logs in dozens of times across all test
    # files, all appearing to originate from the same address under
    # httpx's ASGITransport - doesn't spuriously trip the limiter. A
    # dedicated test (tests/test_rate_limiting.py) enables it explicitly to
    # verify the behavior for real.
    rate_limit_enabled: bool = True

    @model_validator(mode="after")
    def _validate_chunking_config(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"CHUNK_OVERLAP ({self.chunk_overlap}) must be smaller than "
                f"CHUNK_SIZE ({self.chunk_size}), or chunking would never make progress."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
