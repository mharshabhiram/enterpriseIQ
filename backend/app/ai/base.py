"""Provider interfaces. The RAG pipeline depends only on these, so another local
runtime can be plugged in without touching retrieval or prompting code."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(ABC):
    model: str

    @abstractmethod
    def generate(self, messages: list[ChatMessage], *, json_mode: bool = False) -> str: ...


class EmbeddingProvider(ABC):
    model: str
    dimensions: int

    @abstractmethod
    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text], query=True)[0]
