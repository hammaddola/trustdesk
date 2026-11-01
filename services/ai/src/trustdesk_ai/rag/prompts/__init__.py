"""Version-controlled prompts. A prompt's version string is stored on every assistant message."""

from __future__ import annotations

import html
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from trustdesk_ai.retrieval.types import Candidate

_DIR = Path(__file__).parent
ANSWER_PROMPT = "answer.v2"  # v2: citation markers required in every language
REWRITE_PROMPT = "rewrite.v1"

LANGUAGE_NAMES = {"en": "English", "ur": "Urdu (Urdu script)", "ur-Latn": "Roman Urdu (Urdu written in Latin letters)"}


@cache
def load(version: str) -> str:
    path = _DIR / f"{version}.md"
    if not path.is_file() or path.parent != _DIR:
        raise KeyError(version)
    return path.read_text(encoding="utf-8").strip()


def answer_system_prompt(organization: str, language: str, max_sentences: int = 6) -> str:
    return load(ANSWER_PROMPT).format(
        organization=organization,
        language_name=LANGUAGE_NAMES.get(language, "the visitor's language"),
        max_sentences=max_sentences,
    )


def format_evidence(candidates: Sequence[Candidate]) -> str:
    """Evidence block; content is HTML-escaped so a document cannot close the tag and inject text."""
    parts = []
    for i, c in enumerate(candidates, start=1):
        title = html.escape(c.page_title or "", quote=True)
        section = html.escape(c.section or "", quote=True)
        parts.append(f'<evidence id="E{i}" title="{title}" section="{section}">\n{html.escape(c.content)}\n</evidence>')
    return "\n\n".join(parts)


def answer_user_turn(question: str, candidates: Sequence[Candidate]) -> str:
    return f"{format_evidence(candidates)}\n\nVisitor question: {question}"
