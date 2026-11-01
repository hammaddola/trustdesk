"""Cohere embeddings (v2 API), e.g. embed-multilingual-v3.0 (1024 dims). Plain HTTP; no SDK needed."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from trustdesk_ai.providers.base import EmbedKind, ProviderError
from trustdesk_ai.providers.embeddings._check import check_dimensions

COHERE_URL = "https://api.cohere.com/v2/embed"
BATCH = 96  # Cohere's per-request text limit


class CohereEmbeddings:
    name = "cohere"

    def __init__(self, api_key: str, model: str, dimension: int, timeout: float = 60.0) -> None:
        self.model, self.dimension = model, dimension
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    async def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]:
        out: list[list[float]] = []
        input_type = "search_query" if kind == "query" else "search_document"
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as http:
            for i in range(0, len(texts), BATCH):
                batch = list(texts[i : i + BATCH])
                body = {"model": self.model, "texts": batch, "input_type": input_type, "embedding_types": ["float"]}
                try:
                    resp = await http.post(COHERE_URL, json=body)
                except httpx.HTTPError as exc:
                    raise ProviderError(f"cohere unreachable: {type(exc).__name__}") from exc
                if resp.status_code != 200:
                    raise ProviderError(f"cohere embeddings returned HTTP {resp.status_code}")
                out.extend(resp.json()["embeddings"]["float"])
        return check_dimensions(out, self.dimension, self.name, len(texts))
