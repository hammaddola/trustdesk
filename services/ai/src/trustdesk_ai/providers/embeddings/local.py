"""In-process sentence-transformers embeddings (install extra: `pip install trustdesk-ai[local]`)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import anyio

from trustdesk_ai.providers.base import EmbedKind, ProviderError
from trustdesk_ai.providers.embeddings._check import check_dimensions


class LocalEmbeddings:
    name = "local"

    def __init__(self, model: str, dimension: int) -> None:
        self.model, self.dimension = model, dimension
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ProviderError("EMBEDDING_PROVIDER=local needs `pip install trustdesk-ai[local]`") from exc
            self._model = SentenceTransformer(self.model)
        return self._model

    async def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]:
        if not texts:
            return []

        def run() -> list[list[float]]:
            vectors = self._load().encode(list(texts), normalize_embeddings=True, batch_size=16)
            return [list(map(float, v)) for v in vectors]

        vectors = await anyio.to_thread.run_sync(run)  # CPU-bound: keep the event loop free
        return check_dimensions(vectors, self.dimension, self.name, len(texts))
