"""Heading-aware chunking.

Rules:
- Chunks never cross a heading boundary, so every chunk has exactly one section and heading path.
- Blocks are packed up to `max_tokens`; a chunk is closed once it reaches `target_tokens`.
- Tables, lists and code are atomic. If one is larger than `max_tokens` it is split by rows/items,
  and a table's header row is repeated in every piece so each piece stays self-describing.
- Overlap (~15%) is taken from the end of the previous chunk *in the same section*, sentence-aligned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from trustdesk_ai.ingestion.hashing import content_hash
from trustdesk_ai.ingestion.tokens import count_tokens
from trustdesk_ai.ingestion.types import Block, ChunkDraft

# Latin and Urdu/Arabic sentence terminators.
_SENTENCE_END = re.compile(r"(?<=[.!?۔؟])\s+")
_SLUG = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True)
class ChunkConfig:
    target_tokens: int = 500
    max_tokens: int = 600
    overlap_ratio: float = 0.15

    def __post_init__(self) -> None:
        if not (0 < self.target_tokens <= self.max_tokens):
            raise ValueError("require 0 < target_tokens <= max_tokens")
        if not (0 <= self.overlap_ratio < 0.5):
            raise ValueError("overlap_ratio must be in [0, 0.5)")


def _slug(parts: tuple[str, ...]) -> str | None:
    if not parts:
        return None
    return "/".join(_SLUG.sub("-", p.lower()).strip("-") for p in parts)


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def _split_oversized(block: Block, max_tokens: int) -> list[str]:
    """Split a block bigger than max_tokens into pieces at natural boundaries."""
    if block.kind == "table":
        rows = block.text.splitlines()
        header = rows[:2] if len(rows) > 1 and set(rows[1].replace("|", "").strip()) <= set("-: ") else rows[:1]
        body = rows[len(header) :]
        return _pack_units(body, max_tokens, prefix="\n".join(header) + "\n")
    if block.kind in ("list", "code"):
        return _pack_units(block.text.splitlines(), max_tokens)
    units = split_sentences(block.text)
    if len(units) == 1:  # one giant sentence: hard split on words
        words = block.text.split()
        step = max(1, len(words) * max_tokens // max(count_tokens(block.text), 1))
        units = [" ".join(words[i : i + step]) for i in range(0, len(words), step)]
    return _pack_units(units, max_tokens, joiner=" ")


def _pack_units(units: list[str], max_tokens: int, prefix: str = "", joiner: str = "\n") -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    budget = max_tokens - count_tokens(prefix)
    for unit in units:
        candidate = joiner.join([*current, unit])
        if current and count_tokens(candidate) > budget:
            pieces.append(prefix + joiner.join(current))
            current = [unit]
        else:
            current.append(unit)
    if current:
        pieces.append(prefix + joiner.join(current))
    return pieces


def _overlap_tail(text: str, overlap_tokens: int) -> str:
    """Trailing whole sentences totalling at most overlap_tokens."""
    if overlap_tokens <= 0:
        return ""
    tail: list[str] = []
    for sentence in reversed(split_sentences(text)):
        if count_tokens(" ".join([sentence, *tail])) > overlap_tokens:
            break
        tail.insert(0, sentence)
    return " ".join(tail)


def chunk_blocks(blocks: list[Block], config: ChunkConfig | None = None) -> list[ChunkDraft]:
    cfg = config or ChunkConfig()
    overlap_tokens = int(cfg.max_tokens * cfg.overlap_ratio)
    headings: list[tuple[int, str]] = []
    drafts: list[ChunkDraft] = []

    # Accumulator for the current section.
    parts: list[str] = []
    parts_tokens = 0
    page: int | None = None
    previous_in_section: str | None = None

    def path() -> tuple[str, ...]:
        return tuple(text for _, text in headings)

    def emit() -> None:
        nonlocal parts, parts_tokens, page, previous_in_section
        if not parts:
            return
        body = "\n\n".join(parts)
        tail = _overlap_tail(previous_in_section, overlap_tokens) if previous_in_section else ""
        content = f"{tail}\n\n{body}" if tail else body
        hp = path()
        drafts.append(
            ChunkDraft(
                ordinal=len(drafts),
                content=content,
                token_count=count_tokens(content),
                content_hash=content_hash(content),
                heading_path=hp,
                section=hp[-1] if hp else None,
                parent_section_id=_slug(hp[:-1]) if len(hp) > 1 else None,
                page_number=page,
            )
        )
        previous_in_section = body
        parts, parts_tokens, page = [], 0, None

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.kind == "heading":
            emit()
            previous_in_section = None
            level = max(1, min(block.level, 6))
            headings = [(lvl, t) for lvl, t in headings if lvl < level]
            headings.append((level, text))
            continue

        # Body budget leaves room for the overlap tail so content stays within max_tokens.
        limit = cfg.max_tokens - overlap_tokens
        tokens = count_tokens(text)
        pieces = [text] if tokens <= limit else _split_oversized(block, limit)
        for piece in pieces:
            piece_tokens = count_tokens(piece)
            if parts and parts_tokens + piece_tokens > limit:
                emit()
            if page is None:
                page = block.page_number
            parts.append(piece)
            parts_tokens += piece_tokens
            if parts_tokens >= cfg.target_tokens:
                emit()
    emit()
    return drafts


def embedding_text(page_title: str | None, heading_path: tuple[str, ...] | list[str], content: str) -> str:
    """Text sent to the embedding model: title and headings give the chunk its context."""
    context = " > ".join([p for p in [page_title, *heading_path] if p])
    return f"{context}\n\n{content}" if context else content
