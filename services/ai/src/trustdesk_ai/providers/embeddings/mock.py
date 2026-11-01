"""Deterministic dev/test embeddings: hashed bag-of-words, L2-normalized.

Texts sharing words get similar vectors, so retrieval behaves sensibly in tests. Refused in production.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from trustdesk_ai.providers.base import EmbedKind
from trustdesk_ai.rag.text import content_words, stem


class MockEmbeddings:
    name = "mock"
    model = "mock-bow-v1"

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dimension
        for w in content_words(text):
            h = int.from_bytes(hashlib.sha256(stem(w).encode()).digest()[:4], "big")
            v[h % self.dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]:
        return [self._vector(t) for t in texts]
