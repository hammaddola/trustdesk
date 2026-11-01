"""Retrieval candidate passed between retrieval, reranking, the gate and verification."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    content: str
    source_url: str | None
    page_title: str | None
    section: str | None
    heading_path: tuple[str, ...] = ()
    language: str | None = None
    tags: tuple[str, ...] = ()
    source_updated_at: datetime | None = None
    vector_score: float | None = None  # cosine similarity, 0..1
    fts_score: float | None = None  # ts_rank_cd
    rrf_score: float = 0.0
    rerank_score: float | None = None  # normalized 0..1
    extra: dict[str, float] = field(default_factory=dict)

    @property
    def relevance(self) -> float:
        """Best available relevance in 0..1: reranker if it ran, else vector similarity."""
        if self.rerank_score is not None:
            return self.rerank_score
        return self.vector_score or 0.0

    def with_(self, **changes: object) -> Candidate:
        return replace(self, **changes)  # type: ignore[arg-type]
