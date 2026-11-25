"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache
from typing import Annotated

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "EnterpriseIQ"
    database_url: str = "postgresql+psycopg://enterpriseiq:enterpriseiq@localhost:5432/enterpriseiq"

    jwt_secret_key: str = Field(min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "mistral"
    ollama_embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    ollama_timeout_seconds: float = 120
    ollama_num_ctx: int = 8192
    ollama_temperature: float = 0.2
    ollama_startup_wait_seconds: float = 30

    chunk_size: int = 1200
    chunk_overlap: int = 200
    top_k: int = 6
    similarity_threshold: float = 0.45
    max_context_chars: int = 12000
    summary_section_chars: int = 8000

    max_file_size: int = 20 * 1024 * 1024
    upload_dir: str = "./uploads"

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @field_validator("chunk_overlap")
    @classmethod
    def overlap_smaller_than_chunk(cls, value: int, info: ValidationInfo) -> int:
        size = info.data.get("chunk_size", 1200)
        if value < 0 or value >= size // 2:
            raise ValueError("CHUNK_OVERLAP must be between 0 and half of CHUNK_SIZE")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
