"""Hybrid retrieval: vector + full-text -> RRF -> dedupe -> rerank -> top-k."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from trustdesk_ai.ingestion.chunker import embedding_text
from trustdesk_ai.providers.base import RerankerProvider
from trustdesk_ai.retrieval.fusion import rrf_fuse
from trustdesk_ai.retrieval.search import MetadataFilter, fulltext_search, vector_search
from trustdesk_ai.retrieval.types import Candidate


@dataclass(frozen=True)
class RetrievalConfig:
    vector_k: int = 40
    fulltext_k: int = 40
    rrf_k: int = 60
    rerank_pool: int = 40  # how many fused candidates go to the reranker
    top_k: int = 5


@dataclass(frozen=True)
class RetrievalResult:
    vector: list[Candidate]
    fulltext: list[Candidate]
    fused: list[Candidate]


async def hybrid_retrieve(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    query: str,
    query_vector: list[float],
    index_id: UUID,
    dimension: int,
    config: RetrievalConfig,
    filters: MetadataFilter | None = None,
) -> RetrievalResult:
    vec = await vector_search(db, tenant_id, index_id, dimension, query_vector, config.vector_k, filters)
    fts = await fulltext_search(db, tenant_id, query, config.fulltext_k, filters)
    fused = rrf_fuse([vec, fts], k=config.rrf_k, limit=config.rerank_pool)
    # Belt and braces: drop anything that is not this tenant's (RLS and SQL filters should already ensure it).
    fused = [c for c in fused if c.tenant_id == tenant_id]
    return RetrievalResult(vec, fts, fused)


async def rerank(
    reranker: RerankerProvider | None, query: str, candidates: list[Candidate], top_k: int
) -> tuple[list[Candidate], bool]:
    """Returns (top candidates, reranked?). Without a reranker, RRF order is kept."""
    if not candidates:
        return [], reranker is not None
    if reranker is None:
        return candidates[:top_k], False
    scores = await reranker.rerank(query, [embedding_text(c.page_title, c.heading_path, c.content) for c in candidates])
    scored = [c.with_(rerank_score=s) for c, s in zip(candidates, scores, strict=True)]
    scored.sort(key=lambda c: -(c.rerank_score or 0.0))
    return scored[:top_k], True
