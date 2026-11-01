"""Cross-language verification: meaning check only applies across languages; numbers stay strict."""

from tests.factories import TENANT, cand
from trustdesk_ai.rag.verification import CitationVerifier

HOURS = cand("The office is open Monday to Friday, 9:00 to 17:00.", language="en")


def verifier(semantic_score: float) -> tuple[CitationVerifier, list[str]]:
    calls: list[str] = []

    async def scorer(sentence: str, evidence: list[str]) -> float:
        calls.append(sentence)
        return semantic_score

    v = CitationVerifier(TENANT, {1: HOURS}, frozenset({HOURS.document_version_id}), semantic_scorer=scorer)
    return v, calls


async def test_roman_urdu_sentence_accepted_by_meaning():
    v, calls = verifier(0.86)
    r = await v.acheck("Hamara office Monday se Friday, 9:00 se 17:00 tak khula hota hai [E1].")
    assert r.kept and r.text.endswith("[1].") and calls


async def test_low_meaning_similarity_still_dropped():
    v, _ = verifier(0.40)
    r = await v.acheck("Hamara office Monday se Friday, 9:00 se 17:00 tak khula hota hai [E1].")
    assert not r.kept


async def test_invented_number_dropped_even_with_high_similarity():
    v, calls = verifier(0.99)
    r = await v.acheck("Hamara office Monday se Saturday, 8:00 se 20:00 tak khula hota hai [E1].")
    assert not r.kept and "numbers not in evidence" in r.reason and not calls


async def test_same_language_weak_support_is_not_rescued():
    v, calls = verifier(0.99)
    r = await v.acheck("Acme offers penetration testing and cloud migration services [E1].")
    assert not r.kept and not calls  # meaning check never relaxes same-language verification
