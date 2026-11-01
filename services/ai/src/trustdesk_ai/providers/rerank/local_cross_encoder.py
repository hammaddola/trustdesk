"""Local cross-encoder reranker, e.g. BAAI/bge-reranker-v2-m3 (multilingual). Needs the [local] extra."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import anyio

from trustdesk_ai.providers.base import ProviderError


class LocalCrossEncoderReranker:
    name = "local"

    def __init__(self, model: str) -> None:
        self.model = model
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise ProviderError("RERANKER_PROVIDER=local needs `pip install trustdesk-ai[local]`") from exc
            self._model = CrossEncoder(self.model, max_length=512)
        return self._model

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []

        def run() -> list[float]:
            logits = self._load().predict([(query, d) for d in documents], activation_fn=None)
            return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]  # sigmoid -> 0..1

        return await anyio.to_thread.run_sync(run)
