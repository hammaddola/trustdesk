from uuid import uuid4

from tests.factories import cand
from trustdesk_ai.retrieval.fusion import rrf_fuse


def test_rrf_rewards_agreement_and_dedupes():
    a, b, c = cand(), cand(), cand()
    vec = [a, b]
    fts = [c.with_(vector_score=None, fts_score=0.3), a.with_(vector_score=None, fts_score=0.5)]
    fused = rrf_fuse([vec, fts], k=60)
    assert fused[0].chunk_id == a.chunk_id  # present in both lists
    assert len(fused) == 3  # deduped
    assert fused[0].vector_score == a.vector_score and fused[0].fts_score == 0.5  # merged scores
    assert abs(fused[0].rrf_score - (1 / 61 + 1 / 62)) < 1e-12


def test_rrf_limit_and_empty():
    assert rrf_fuse([[], []]) == []
    assert len(rrf_fuse([[cand() for _ in range(5)]], limit=2)) == 2


def test_rrf_deterministic_tie_break():
    x, y = cand(chunk_id=uuid4()), cand(chunk_id=uuid4())
    assert [c.chunk_id for c in rrf_fuse([[x], [y]])] == [c.chunk_id for c in rrf_fuse([[y], [x]])]
