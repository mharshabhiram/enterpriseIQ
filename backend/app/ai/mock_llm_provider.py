"""
Mock LLM provider.

Deterministic and offline, like MockEmbeddingProvider. Records the exact
messages it was last called with (`last_messages`) so tests can assert on
prompt construction directly - what context actually made it into the
prompt, whether the LLM was even called at all - rather than needing to
parse a real (and non-deterministic) generated answer.

Never use in production - set LLM_PROVIDER=openai with a real LLM_API_KEY
for actual answer generation.
"""
from typing import List, Optional

from app.ai.llm_provider import ChatMessage, LLMProvider

_DEFAULT_RESPONSE = "This is a mock response. Configure LLM_PROVIDER=openai for real answers."


class MockLLMProvider(LLMProvider):
    def __init__(self, response: Optional[str] = None):
        self._response = response if response is not None else _DEFAULT_RESPONSE
        self.last_messages: List[ChatMessage] = []
        self.call_count = 0

    async def generate(self, messages: List[ChatMessage]) -> str:
        self.last_messages = messages
        self.call_count += 1
        return self._response
