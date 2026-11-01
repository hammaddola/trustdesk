"""Deterministic answerability policy, run BEFORE generation (no model call on refusal).

The policy uses only retrieval evidence; it does not depend on which LLM is configured.
Every decision records its signals and reasons so the admin Playground can explain refusals.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from trustdesk_ai.rag.text import content_words, lexical_coverage
from trustdesk_ai.retrieval.types import Candidate


@dataclass(frozen=True)
class AnswerabilityPolicy:
    min_relevance: float = 0.35  # tenant `confidence_threshold`
    reranker_none_penalty: float = 0.15  # stricter when no reranker scored candidates
    min_supporting_chunks: int = 1
    min_query_coverage: float = 0.34  # share of query content words found in evidence (same-language only)
    # Above this relevance the evidence clearly matches by meaning; literal word coverage is not required
    # (paraphrases like "outside your city" vs "remotely" would otherwise be refused).
    coverage_exempt_relevance: float = 0.8
    stale_after_days: int = 365
    required_tags: tuple[str, ...] = ()  # e.g. ("founder",) for Ask the Founder (P2)


@dataclass(frozen=True)
class GateDecision:
    answerable: bool
    reasons: tuple[str, ...]
    signals: dict[str, float | int | bool | None] = field(default_factory=dict)
    supporting: tuple[Candidate, ...] = ()


def evaluate(
    query: str,
    query_language: str | None,
    candidates: Sequence[Candidate],
    policy: AnswerabilityPolicy,
    *,
    reranked: bool,
    now: datetime | None = None,
) -> GateDecision:
    now = now or datetime.now(UTC)
    threshold = policy.min_relevance + (0.0 if reranked else policy.reranker_none_penalty)
    reasons: list[str] = []

    eligible = [c for c in candidates if all(t in c.tags for t in policy.required_tags)]
    if policy.required_tags and len(eligible) < len(candidates):
        reasons.append(f"excluded {len(candidates) - len(eligible)} chunks without tags {policy.required_tags}")
    supporting = [c for c in eligible if c.relevance >= threshold]
    top = max((c.relevance for c in eligible), default=0.0)

    same_language = [c for c in supporting if not query_language or not c.language or c.language == query_language]
    terms = content_words(query)
    coverage: float | None = (
        lexical_coverage(terms, [c.content + " " + (c.page_title or "") for c in same_language])
        if same_language and terms
        else None  # cross-language or no content words: lexical coverage is not meaningful
    )

    stale_cutoff = now - timedelta(days=policy.stale_after_days)
    fresh = [c for c in supporting if c.source_updated_at is None or c.source_updated_at >= stale_cutoff]

    answerable = True
    if not eligible:
        answerable = False
        reasons.append("no evidence retrieved")
    elif len(supporting) < policy.min_supporting_chunks:
        answerable = False
        reasons.append(f"top relevance {top:.2f} below threshold {threshold:.2f}")
    if (
        answerable
        and coverage is not None
        and coverage < policy.min_query_coverage
        and top < policy.coverage_exempt_relevance
    ):
        answerable = False
        reasons.append(f"evidence covers {coverage:.0%} of the question's key terms")
    if answerable and supporting and not fresh:
        reasons.append("all supporting sources are older than the freshness limit")  # lowers confidence only
    if answerable:
        reasons.append(f"{len(supporting)} supporting chunk(s), top relevance {top:.2f}")

    return GateDecision(
        answerable=answerable,
        reasons=tuple(reasons),
        signals={
            "top_relevance": round(top, 4),
            "threshold": round(threshold, 4),
            "supporting_chunks": len(supporting),
            "query_coverage": None if coverage is None else round(coverage, 4),
            "fresh_supporting_chunks": len(fresh),
            "reranked": reranked,
            "contradiction": None,  # P2: source conflict detection
        },
        supporting=tuple(supporting),
    )
