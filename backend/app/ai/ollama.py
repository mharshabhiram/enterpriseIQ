"""Ollama implementations of the provider interfaces (local HTTP API, no API keys)."""
import time

import httpx

from app.ai.base import ChatMessage, EmbeddingProvider, LLMProvider
from app.config import Settings, get_settings
from app.exceptions import EmbeddingUnavailable, LLMUnavailable
from app.logging_config import get_logger

log = get_logger(__name__)

# nomic-embed-text expects task prefixes for best retrieval quality.
_NOMIC_DOC_PREFIX = "search_document: "
_NOMIC_QUERY_PREFIX = "search_query: "


def _client(settings: Settings) -> httpx.Client:
    return httpx.Client(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds)


def _model_missing(response: httpx.Response) -> bool:
    return response.status_code == 404 or "not found" in response.text.lower()


class OllamaLLMProvider(LLMProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.ollama_llm_model

    def generate(self, messages: list[ChatMessage], *, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": self.settings.ollama_temperature, "num_ctx": self.settings.ollama_num_ctx},
        }
        if json_mode:
            payload["format"] = "json"
        started = time.perf_counter()
        try:
            with _client(self.settings) as client:
                response = client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable("The local model took too long to respond. Try a shorter request.") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                f"Cannot reach Ollama at {self.settings.ollama_base_url}. Is the Ollama service running?"
            ) from exc
        if response.status_code != 200:
            if _model_missing(response):
                raise LLMUnavailable(f"Model '{self.model}' is not installed. Run: ollama pull {self.model}")
            raise LLMUnavailable(f"Ollama returned an error ({response.status_code}).")
        content = (response.json().get("message") or {}).get("content", "").strip()
        log.info("llm_generate", model=self.model, ms=round((time.perf_counter() - started) * 1000))
        if not content:
            raise LLMUnavailable("The local model returned an empty response.")
        return content


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, settings: Settings | None = None, batch_size: int = 32) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.ollama_embedding_model
        self.dimensions = self.settings.embedding_dimensions
        self.batch_size = batch_size

    def _prefix(self, text: str, query: bool) -> str:
        if "nomic" in self.model:
            return (_NOMIC_QUERY_PREFIX if query else _NOMIC_DOC_PREFIX) + text
        return text

    def _post(self, inputs: list[str]) -> list[list[float]]:
        try:
            with _client(self.settings) as client:
                response = client.post("/api/embed", json={"model": self.model, "input": inputs})
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(
                f"Cannot reach Ollama at {self.settings.ollama_base_url} for embeddings."
            ) from exc
        if response.status_code != 200:
            if _model_missing(response):
                raise EmbeddingUnavailable(f"Embedding model '{self.model}' is not installed. Run: ollama pull {self.model}")
            raise EmbeddingUnavailable(f"Ollama embedding error ({response.status_code}).")
        vectors: list[list[float]] = response.json().get("embeddings") or []
        if len(vectors) != len(inputs):
            raise EmbeddingUnavailable("Ollama returned an incomplete embedding batch.")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingUnavailable(
                    f"Embedding size mismatch: model '{self.model}' returned {len(vector)} dimensions, "
                    f"but EMBEDDING_DIMENSIONS={self.dimensions}. Fix the setting and re-embed documents."
                )
        return vectors

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._post([self._prefix(t, query) for t in texts[i : i + self.batch_size]]))
        return out
