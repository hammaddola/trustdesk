from datetime import UTC, datetime, timedelta

from tests.factories import cand
from trustdesk_ai.rag.answerability import AnswerabilityPolicy, evaluate
from trustdesk_ai.rag.confidence import confidence_level

P = AnswerabilityPolicy(min_relevance=0.35)
Q = "Do you design websites for small businesses?"


def test_no_evidence_refuses():
    d = evaluate(Q, "en", [], P, reranked=True)
    assert not d.answerable and "no evidence retrieved" in d.reasons


def test_low_relevance_refuses():
    d = evaluate(Q, "en", [cand(rerank=0.1)], P, reranked=True)
    assert not d.answerable and "below threshold" in d.reasons[0]


def test_relevant_and_covered_is_answerable():
    d = evaluate(Q, "en", [cand(rerank=0.9), cand(rerank=0.8)], P, reranked=True)
    assert d.answerable and d.signals["supporting_chunks"] == 2


def test_borderline_relevance_with_off_topic_terms_refuses():
    d = evaluate("What is your refund policy for enterprise contracts?", "en", [cand(rerank=0.6)], P, reranked=True)
    assert not d.answerable and "covers" in d.reasons[-1]


def test_strong_relevance_allows_paraphrase():
    faq = cand("Yes. Acme Studio works with clients remotely and holds meetings by video call.", rerank=0.82)
    d = evaluate("Do you work with clients outside your city?", "en", [faq], P, reranked=True)
    assert d.answerable


def test_stem_handles_plural_and_verb_forms():
    from trustdesk_ai.rag.text import stem

    assert stem("work") == stem("works") == stem("worked") == stem("working")
    assert stem("clients") == stem("client")


def test_stricter_without_reranker():
    c = [cand(vector=0.4, rerank=None)]
    assert evaluate(Q, "en", c, P, reranked=True).answerable
    assert not evaluate(Q, "en", c, P, reranked=False).answerable


def test_cross_language_skips_lexical_coverage():
    d = evaluate("کیا آپ ویب سائٹس بناتے ہیں؟", "ur", [cand(rerank=0.9, language="en")], P, reranked=True)
    assert d.answerable and d.signals["query_coverage"] is None


def test_required_tags_filter():
    p = AnswerabilityPolicy(required_tags=("founder",))
    assert not evaluate(Q, "en", [cand(rerank=0.9)], p, reranked=True).answerable
    assert evaluate(Q, "en", [cand(rerank=0.9, tags=("founder",))], p, reranked=True).answerable


def test_confidence_levels():
    gate = evaluate(Q, "en", [cand(rerank=0.9), cand(rerank=0.8)], P, reranked=True)
    assert confidence_level(gate, 1.0) == "high"
    assert confidence_level(gate, 0.8) == "medium"
    assert confidence_level(gate, 0.5) == "low"
    old = datetime.now(UTC) - timedelta(days=800)
    stale = evaluate(Q, "en", [cand(rerank=0.9, updated=old), cand(rerank=0.8, updated=old)], P, reranked=True)
    assert confidence_level(stale, 1.0) == "medium"  # stale sources cap confidence below high
    assert confidence_level(evaluate(Q, "en", [], P, reranked=True), 1.0) == "low"
