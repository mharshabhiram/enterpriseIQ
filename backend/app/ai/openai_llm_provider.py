"""
OpenAI-compatible LLM provider.

Same approach as app.ai.openai_embedding_provider: raw HTTP (httpx) against
POST {base_url}/chat/completions rather than a vendor SDK, so any
OpenAI-compatible server works by changing LLM_BASE_URL.
"""
from typing import List

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.ai.llm_provider import ChatMessage, LLMProvider
from app.utils.errors import LLMProviderError

_DEFAULT_TIMEOUT_SECONDS = 60.0
# Low temperature: this provider is used for factual RAG answering, where
# consistency and grounding in the provided context matter far more than
# creative variation.
_DEFAULT_TEMPERATURE = 0.2


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        temperature: float = _DEFAULT_TEMPERATURE,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._timeout = timeout

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _post_chat_completion(self, messages: List[ChatMessage]) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "messages": messages, "temperature": self._temperature},
            )
            response.raise_for_status()
            return response.json()

    async def generate(self, messages: List[ChatMessage]) -> str:
        if not self._api_key:
            raise LLMProviderError(
                "LLM_API_KEY is not configured. Set it in the environment, or set "
                "LLM_PROVIDER=mock for local development/testing without an API key."
            )

        try:
            payload = await self._post_chat_completion(messages)
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"LLM provider returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.TransportError as exc:
            raise LLMProviderError(f"Could not reach the LLM provider: {exc}") from exc

        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                f"LLM provider returned an unexpected response shape: {payload!r}"
            ) from exc
