"""Ollama embeddings (e.g. bge-m3, 1024 dims, multilingual)."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from trustdesk_ai.providers.base import EmbedKind, ProviderError
from trustdesk_ai.providers.embeddings._check import check_dimensions


class OllamaEmbeddings:
    name = "ollama"

    def __init__(self, base_url: str, model: str, dimension: int, timeout: float = 120.0) -> None:
        self.model, self.dimension = model, dimension
        self._base, self._timeout = base_url.rstrip("/"), timeout

    async def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                resp = await http.post(f"{self._base}/api/embed", json={"model": self.model, "input": list(texts)})
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama unreachable: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"ollama embeddings returned HTTP {resp.status_code}")
        return check_dimensions(resp.json()["embeddings"], self.dimension, self.name, len(texts))
