"""
EmbeddingProvider abstract interface (project brief section 33).

Anything that can turn text into vectors implements this - the rest of the
codebase (embedding_service, retrieval_service) only ever depends on this
interface, never on a concrete provider, so adding a new embedding backend
means writing one new class here and one line in the factory - never
touching the ingestion or search pipelines.
"""
from abc import ABC, abstractmethod
from typing import List


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts, returning one vector per input in the same order."""
        raise NotImplementedError
