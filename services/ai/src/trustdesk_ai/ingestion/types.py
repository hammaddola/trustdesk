"""Parser output: an ordered list of typed blocks, independent of the source format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "list", "table", "code"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    level: int = 0  # heading level 1-6; 0 for non-headings
    page_number: int | None = None


@dataclass
class ParsedDocument:
    blocks: list[Block]
    title: str | None = None
    language: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    content: str
    token_count: int
    content_hash: str
    heading_path: tuple[str, ...]
    section: str | None
    parent_section_id: str | None
    page_number: int | None
