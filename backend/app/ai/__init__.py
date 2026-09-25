"""AI provider abstraction layer (project brief section 33)."""
from app.ai.embedding_provider import EmbeddingProvider
from app.ai.factory import get_embedding_provider, get_llm_provider
from app.ai.llm_provider import ChatMessage, LLMProvider
from app.ai.mock_embedding_provider import MockEmbeddingProvider
from app.ai.mock_llm_provider import MockLLMProvider
from app.ai.openai_embedding_provider import OpenAICompatibleEmbeddingProvider
from app.ai.openai_llm_provider import OpenAICompatibleLLMProvider

__all__ = [
    "EmbeddingProvider",
    "LLMProvider",
    "ChatMessage",
    "get_embedding_provider",
    "get_llm_provider",
    "MockEmbeddingProvider",
    "MockLLMProvider",
    "OpenAICompatibleEmbeddingProvider",
    "OpenAICompatibleLLMProvider",
]
