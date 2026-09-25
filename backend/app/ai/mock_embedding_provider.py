"""
Mock embedding provider.

Deterministic and offline: the same text always maps to the same unit
vector (hashed into a seed, then a normalized pseudo-random vector), and
different texts map to different vectors. It has zero semantic
understanding - it's not a real embedding model - but it exercises the
*entire* rest of the pipeline for real: chunk storage, the pgvector
similarity query, ranking, and RBAC filtering all run against genuine
vectors and a genuine cosine-distance index, just not ones that encode
real meaning.

Two legitimate uses:
1. EMBEDDING_PROVIDER=mock lets the whole application run - uploads,
   processing, search - without any embedding API key at all, which
   matters for a university project a grader may want to run without
   supplying credentials.
2. It's what the test suite injects into the ingestion/search pipeline
   instead of making real network calls.

Never use this in a real deployment - set EMBEDDING_PROVIDER=openai (the
default) with a real EMBEDDING_API_KEY for actual semantic search quality.
"""
import hashlib
import random
from typing import List

from app.ai.embedding_provider import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int):
        self._dimensions = dimensions

    async def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> List[float]:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        rng = random.Random(seed)
        vector = [rng.uniform(-1.0, 1.0) for _ in range(self._dimensions)]
        norm = sum(v * v for v in vector) ** 0.5 or 1.0
        return [v / norm for v in vector]
