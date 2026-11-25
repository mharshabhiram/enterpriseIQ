"""Provider factory — the only place that decides which AI runtime is used (Ollama)."""
from functools import lru_cache

from app.ai.base import EmbeddingProvider, LLMProvider
from app.ai.ollama import OllamaEmbeddingProvider, OllamaLLMProvider


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return OllamaEmbeddingProvider()


@lru_cache
def get_llm_provider() -> LLMProvider:
    return OllamaLLMProvider()
