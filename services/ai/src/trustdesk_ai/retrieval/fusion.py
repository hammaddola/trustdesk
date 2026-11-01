"""Reciprocal Rank Fusion (Cormack et al., 2009): score = sum over lists of 1 / (k + rank)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from trustdesk_ai.retrieval.types import Candidate


def rrf_fuse(ranked_lists: Sequence[Sequence[Candidate]], k: int = 60, limit: int | None = None) -> list[Candidate]:
    """Fuse ranked lists, dedupe by chunk_id, keep the best per-retriever scores seen for each chunk."""
    scores: dict[object, float] = {}
    merged: dict[object, Candidate] = {}
    for ranked in ranked_lists:
        for rank, cand in enumerate(ranked, start=1):
            scores[cand.chunk_id] = scores.get(cand.chunk_id, 0.0) + 1.0 / (k + rank)
            prev = merged.get(cand.chunk_id)
            if prev is None:
                merged[cand.chunk_id] = cand
            else:
                merged[cand.chunk_id] = replace(
                    prev,
                    vector_score=prev.vector_score if prev.vector_score is not None else cand.vector_score,
                    fts_score=prev.fts_score if prev.fts_score is not None else cand.fts_score,
                )
    fused = [replace(c, rrf_score=scores[cid]) for cid, c in merged.items()]
    fused.sort(key=lambda c: (-c.rrf_score, str(c.chunk_id)))
    return fused[:limit] if limit is not None else fused
