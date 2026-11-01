"""Small text utilities shared by the gate and the verifier."""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

STOPWORDS = frozenset(
    """a an and are as at be been but by can could do does did for from has have how i if in into is it its
    me my no not of on or our so than that the their them then there these they this to us was we were what
    when where which who why will with would you your about any all also more most such only own same just
    should may might must shall tell give please know want need get yes hai hain ka ki ke ko se mein main
    aap kya kia ye yeh wo woh hum tum aur bhi to nahi nahin""".split()
)


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(unicodedata.normalize("NFKC", text))]


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and len(w) > 1 and not w.isdigit()]


_SUFFIXES = ("ing", "ed", "es", "s")


def stem(word: str) -> str:
    # shortcut: crude suffix strip + 5-char prefix (language-agnostic); upgrade to per-language-pack stemmers in P2.
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:5]


def numbers(text: str) -> set[str]:
    """Numeric tokens normalized (thousand separators removed, trailing .0 dropped)."""
    out = set()
    for raw in _NUMBER.findall(unicodedata.normalize("NFKC", text)):
        n = raw.replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def lexical_coverage(query_terms: list[str], texts: list[str]) -> float:
    """Fraction of query content terms (stemmed) that appear in any of the texts."""
    if not query_terms:
        return 0.0
    vocab = {stem(w) for t in texts for w in words(t)}
    hits = sum(1 for w in query_terms if stem(w) in vocab)
    return hits / len(query_terms)
