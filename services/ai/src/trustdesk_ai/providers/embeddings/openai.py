"""OpenAI embeddings. text-embedding-3-* support the `dimensions` parameter (we request EMBEDDING_DIMENSION)."""

from __future__ import annotations

from collections.abc import Sequence

import openai

from trustdesk_ai.providers.base import EmbedKind, ProviderError
from trustdesk_ai.providers.embeddings._check import check_dimensions


class OpenAIEmbeddings:
    def __init__(self, api_key: str, model: str, dimension: int, base_url: str | None = None) -> None:
        self.name = "openai"
        self.model, self.dimension = model, dimension
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=2)

    async def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = await self._client.embeddings.create(model=self.model, input=list(texts), dimensions=self.dimension)
        except openai.APIError as exc:
            raise ProviderError(f"openai embeddings failed: {type(exc).__name__}") from exc
        data = list(resp.data)
        # Some OpenAI-compatible servers (e.g. Gemini) omit `index`; they return items in input order.
        if all(d.index is not None for d in data):
            data.sort(key=lambda d: d.index)
        vectors = [d.embedding for d in data]
        return check_dimensions(vectors, self.dimension, self.name, len(texts))
