"""Visitor-facing confidence: quality and coverage of evidence, NOT a guarantee of correctness.

Rules (explicit, documented in docs/architecture.md):
HIGH   — answerable, top relevance >= high_relevance, >= 2 supporting chunks, every sentence verified,
         at least one fresh supporting source.
MEDIUM — answerable and >= 75% of sentences verified.
LOW    — anything else that still produced a verified answer (visitor is offered human help).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trustdesk_ai.rag.answerability import GateDecision

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class ConfidencePolicy:
    high_relevance: float = 0.7
    high_min_supporting: int = 2
    medium_min_kept_ratio: float = 0.75


def confidence_level(gate: GateDecision, kept_ratio: float, policy: ConfidencePolicy | None = None) -> Confidence:
    p = policy or ConfidencePolicy()
    if not gate.answerable:
        return "low"
    top = float(gate.signals.get("top_relevance") or 0.0)
    supporting = int(gate.signals.get("supporting_chunks") or 0)
    fresh = int(gate.signals.get("fresh_supporting_chunks") or 0)
    if top >= p.high_relevance and supporting >= p.high_min_supporting and kept_ratio >= 1.0 and fresh > 0:
        return "high"
    if kept_ratio >= p.medium_min_kept_ratio:
        return "medium"
    return "low"
