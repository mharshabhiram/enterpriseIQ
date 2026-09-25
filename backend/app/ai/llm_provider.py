"""
LLMProvider abstract interface (project brief section 33).

Anything that can turn a chat-style message list into a generated response
implements this - rag_service depends only on this interface, never on a
concrete provider.
"""
from abc import ABC, abstractmethod
from typing import List, TypedDict


class ChatMessage(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, messages: List[ChatMessage]) -> str:
        """Generate a response for the given message history, returning the text content."""
        raise NotImplementedError
