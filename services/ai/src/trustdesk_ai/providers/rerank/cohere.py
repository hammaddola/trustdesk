"""Cohere rerank (v2 API), e.g. rerank-multilingual-v3.0. relevance_score is already 0..1."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from trustdesk_ai.providers.base import ProviderError

COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"


class CohereReranker:
    name = "cohere"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        body = {"model": self.model, "query": query, "documents": list(documents), "top_n": len(documents)}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as http:
                resp = await http.post(COHERE_RERANK_URL, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"cohere unreachable: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"cohere rerank returned HTTP {resp.status_code}")
        scores = [0.0] * len(documents)
        for item in resp.json()["results"]:
            scores[item["index"]] = float(item["relevance_score"])
        return scores
