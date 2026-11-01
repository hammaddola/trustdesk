"""Independent citation verification.

The model sees evidence labelled [E1]..[En]. It never sees chunk IDs, and its markers are only
accepted if they map to this request's evidence set. Each sentence is checked on its own so the
stream can emit verified sentences as they complete (decision D6 in docs/architecture.md).

Checks per sentence:
1. Every marker maps to evidence in this request's retrieval set, for this tenant, on an active version.
2. Factual sentences must carry at least one valid marker.
3. Every number in the sentence (prices, percentages, dates, counts) appears in the cited evidence.
4. Lexical support: enough of the sentence's content words appear in the cited evidence.

This is a conservative proxy for entailment, not a proof (risk R3). On doubt, the sentence is dropped.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from trustdesk_ai.rag.text import content_words, numbers, stem, words
from trustdesk_ai.retrieval.types import Candidate

MARKER = re.compile(r"\[E(\d{1,2})\]")
_ANY_BRACKET_REF = re.compile(r"\[(?:E|S|Source|source|\^)?\s*\d{1,3}\]")

# Sentences that state the absence of information are allowed without a citation (no claim is made).
_UNCERTAINTY = re.compile(
    r"\b(i (do not|don't) have|not (documented|mentioned|stated|available) in|(could not|couldn't) find|"
    r"no information|the (sources|documents) do not)\b",
    re.IGNORECASE,
)

SupportScorer = Callable[[str, list[str]], float]
# Async meaning-level scorer (embedding cosine) used ONLY when the sentence's language differs from the
# evidence's, where word overlap cannot work. Numbers must still appear verbatim in the evidence.
SemanticScorer = Callable[[str, list[str]], Awaitable[float]]


def lexical_support(sentence: str, evidence: list[str]) -> float:
    terms = content_words(MARKER.sub("", sentence))
    if not terms:
        return 1.0
    vocab = {stem(w) for text in evidence for w in words(text)}
    return sum(1 for t in terms if stem(t) in vocab) / len(terms)


def best_span(sentence: str, evidence: str) -> str:
    """Evidence sentence with the highest term overlap (stored as the supporting span)."""
    from trustdesk_ai.ingestion.chunker import split_sentences

    terms = {stem(w) for w in content_words(MARKER.sub("", sentence))}
    best, best_score = "", -1
    for candidate in split_sentences(evidence) or [evidence]:
        score = len(terms & {stem(w) for w in words(candidate)})
        if score > best_score:
            best, best_score = candidate, score
    return best[:1000]


@dataclass(frozen=True)
class VerifiedCitation:
    marker: int  # renumbered, 1..n in order of first use
    candidate: Candidate
    supporting_span: str
    support_score: float


@dataclass(frozen=True)
class SentenceVerdict:
    original: str
    kept: bool
    text: str  # with markers renumbered to [1], [2] ... (empty when dropped)
    reason: str
    new_citations: tuple[VerifiedCitation, ...] = ()


@dataclass
class CitationVerifier:
    tenant_id: UUID
    evidence: Mapping[int, Candidate]  # E-number -> candidate (this request's retrieval set)
    active_version_ids: frozenset[UUID]
    min_support: float = 0.5
    scorer: SupportScorer = lexical_support
    semantic_scorer: SemanticScorer | None = None
    semantic_min: float = 0.75
    citations: dict[int, VerifiedCitation] = field(default_factory=dict)  # E-number -> citation
    verdicts: list[SentenceVerdict] = field(default_factory=list)

    def _valid(self, e: int) -> Candidate | None:
        cand = self.evidence.get(e)
        if cand is None or cand.tenant_id != self.tenant_id:
            return None
        if cand.document_version_id not in self.active_version_ids:
            return None
        return cand

    def check(self, sentence: str) -> SentenceVerdict:
        verdict = self._check(sentence.strip())
        self.verdicts.append(verdict)
        return verdict

    async def acheck(self, sentence: str) -> SentenceVerdict:
        """Like check(), plus a cross-language meaning check when word overlap is too weak."""
        sentence = sentence.strip()
        verdict = self._check(sentence)
        if not verdict.kept and verdict.reason.startswith("weak support") and self.semantic_scorer is not None:
            cited = [self.evidence[int(m)] for m in dict.fromkeys(MARKER.findall(sentence))]
            if self._cross_language(sentence, cited):
                score = await self.semantic_scorer(MARKER.sub("", sentence), [c.content for c in cited])
                if score >= self.semantic_min:
                    verdict = self._check(sentence, support_override=score)
        self.verdicts.append(verdict)
        return verdict

    @staticmethod
    def _cross_language(sentence: str, cited: list[Candidate]) -> bool:
        from trustdesk_ai.rag.language import detect_language

        lang = detect_language(MARKER.sub("", sentence))
        return any(c.language and c.language != lang for c in cited)

    def _check(self, sentence: str, support_override: float | None = None) -> SentenceVerdict:
        if not sentence:
            return SentenceVerdict(sentence, False, "", "empty")
        markers = [int(m) for m in MARKER.findall(sentence)]
        stripped = MARKER.sub("", sentence)
        if _ANY_BRACKET_REF.search(stripped):
            return SentenceVerdict(sentence, False, "", "unrecognized citation format")
        if not markers:
            if _UNCERTAINTY.search(sentence) and not numbers(sentence):
                return SentenceVerdict(sentence, True, sentence, "uncertainty statement")
            return SentenceVerdict(sentence, False, "", "uncited claim")

        cited: list[tuple[int, Candidate]] = []
        for e in dict.fromkeys(markers):
            cand = self._valid(e)
            if cand is None:
                return SentenceVerdict(sentence, False, "", f"invalid citation [E{e}]")
            cited.append((e, cand))
        texts = [c.content for _, c in cited]

        missing = numbers(stripped) - set().union(*(numbers(t) for t in texts))
        if missing:
            return SentenceVerdict(sentence, False, "", f"numbers not in evidence: {sorted(missing)}")

        score = support_override if support_override is not None else self.scorer(stripped, texts)
        if support_override is None and score < self.min_support:
            return SentenceVerdict(sentence, False, "", f"weak support {score:.2f}")

        new: list[VerifiedCitation] = []
        for e, cand in cited:
            if e not in self.citations:
                vc = VerifiedCitation(len(self.citations) + 1, cand, best_span(stripped, cand.content), score)
                self.citations[e] = vc
                new.append(vc)
        text = MARKER.sub(lambda m: f"[{self.citations[int(m.group(1))].marker}]", sentence)
        return SentenceVerdict(sentence, True, text, f"supported {score:.2f}", tuple(new))

    @property
    def kept_claims(self) -> int:
        return sum(1 for v in self.verdicts if v.kept and v.reason.startswith("supported"))

    @property
    def dropped(self) -> int:
        return sum(1 for v in self.verdicts if not v.kept and v.reason != "empty")

    @property
    def kept_ratio(self) -> float:
        considered = [v for v in self.verdicts if v.reason != "empty"]
        return sum(1 for v in considered if v.kept) / len(considered) if considered else 0.0

    def sufficient(self, min_kept_ratio: float = 0.5) -> bool:
        """An answer needs at least one verified claim and must not have lost most of its sentences."""
        return self.kept_claims >= 1 and self.kept_ratio >= min_kept_ratio
