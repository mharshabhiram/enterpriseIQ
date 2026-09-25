"""
OpenAI-compatible embedding provider.

Uses raw HTTP (httpx) against POST {base_url}/embeddings rather than a
vendor SDK, so anything that speaks the same wire format - OpenAI itself,
Azure OpenAI-compatible proxies, or a self-hosted server (vLLM, Ollama,
etc.) - works by changing EMBEDDING_BASE_URL, with no code changes.
"""
from typing import List

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.ai.embedding_provider import EmbeddingProvider
from app.utils.errors import EmbeddingProviderError

_DEFAULT_TIMEOUT_SECONDS = 30.0


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, api_key: str, model: str, base_url: str, timeout: float = _DEFAULT_TIMEOUT_SECONDS):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _post_embeddings(self, texts: List[str]) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
            return response.json()

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not self._api_key:
            raise EmbeddingProviderError(
                "EMBEDDING_API_KEY is not configured. Set it in the environment, or set "
                "EMBEDDING_PROVIDER=mock for local development/testing without an API key."
            )
        if not texts:
            return []

        try:
            payload = await self._post_embeddings(texts)
        except httpx.HTTPStatusError as exc:
            raise EmbeddingProviderError(
                f"Embedding provider returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.TransportError as exc:
            raise EmbeddingProviderError(f"Could not reach the embedding provider: {exc}") from exc

        try:
            items = sorted(payload["data"], key=lambda item: item["index"])
            return [item["embedding"] for item in items]
        except (KeyError, TypeError) as exc:
            raise EmbeddingProviderError(
                f"Embedding provider returned an unexpected response shape: {payload!r}"
            ) from exc
