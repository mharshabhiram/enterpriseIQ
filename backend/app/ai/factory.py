"""Factory for the configured EmbeddingProvider/LLMProvider - the only place that reads EMBEDDING_PROVIDER/LLM_PROVIDER."""
from app.ai.embedding_provider import EmbeddingProvider
from app.ai.llm_provider import LLMProvider
from app.ai.mock_embedding_provider import MockEmbeddingProvider
from app.ai.mock_llm_provider import MockLLMProvider
from app.ai.openai_embedding_provider import OpenAICompatibleEmbeddingProvider
from app.ai.openai_llm_provider import OpenAICompatibleLLMProvider
from app.config import settings

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.embedding_provider.lower()

    if provider == "mock":
        return MockEmbeddingProvider(dimensions=settings.embedding_dimensions)

    if provider == "openai":
        return OpenAICompatibleEmbeddingProvider(
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url or _DEFAULT_OPENAI_BASE_URL,
        )

    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}'. "
        "Supported values: 'openai', 'mock'."
    )


def get_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()

    if provider == "mock":
        return MockLLMProvider()

    if provider == "openai":
        return OpenAICompatibleLLMProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url or _DEFAULT_OPENAI_BASE_URL,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Supported values: 'openai', 'mock'."
    )
