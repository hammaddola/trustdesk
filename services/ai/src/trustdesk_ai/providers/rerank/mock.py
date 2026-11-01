"""Dev/test reranker: share of query content words found in the document. Refused in production."""

from __future__ import annotations

from collections.abc import Sequence

from trustdesk_ai.rag.text import content_words, lexical_coverage


class MockReranker:
    name = "mock"
    model = "mock-lexical-v1"

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        terms = content_words(query)
        return [lexical_coverage(terms, [d]) for d in documents]
