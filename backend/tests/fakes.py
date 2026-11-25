"""Deterministic stand-ins for Ollama so the suite runs without models."""
import hashlib
import json
import math
import re

from app.ai.base import ChatMessage, EmbeddingProvider, LLMProvider

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "and", "is", "are", "in", "for", "on", "what", "how", "do", "i", "my", "with", "be"}


class FakeEmbedder(EmbeddingProvider):
    """Bag-of-words hashed into 768 dims: texts sharing words have high cosine similarity."""

    model = "nomic-embed-text"
    dimensions = 768

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dimensions
        for word in _WORD.findall(text.lower()):
            if word not in _STOP:
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dimensions] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v] if any(v) else [1.0 / math.sqrt(self.dimensions)] * self.dimensions

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class FakeLLM(LLMProvider):
    model = "mistral"

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    def generate(self, messages: list[ChatMessage], *, json_mode: bool = False) -> str:
        self.calls.append(messages)
        if json_mode:
            return json.dumps(
                {
                    "overview": "B extends A.",
                    "key_differences": ["Leave increased"],
                    "categories": [{"name": "Added", "changes": [{"type": "added", "topic": "Leave", "document_a": "", "document_b": "25 days", "explanation": "More leave"}]}],
                }
            )
        if "[S1]" in messages[-1].content:
            return "Employees receive 25 days of annual leave [S1]."
        return "Summary: key points of the document."
