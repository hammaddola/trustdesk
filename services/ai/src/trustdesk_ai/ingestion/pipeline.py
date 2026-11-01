"""Index one parsed document: version -> chunk -> embed -> activate.

Guarantees (decision D12):
- Unchanged content (same normalized hash as the active version) is skipped: no new version, no embedding cost.
- A new version is built in state `building`; only after every chunk is embedded does one transaction
  switch `documents.active_version_id`. A failure marks the new version `failed` and leaves the
  previous active version serving.
- Chunk embeddings are reused when an identical chunk (same content hash) was already embedded in the
  same embedding index.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from trustdesk_ai.db.models import Chunk, ChunkEmbedding, Document, DocumentVersion, EmbeddingIndex
from trustdesk_ai.ingestion.chunker import ChunkConfig, chunk_blocks, embedding_text
from trustdesk_ai.ingestion.hashing import content_hash
from trustdesk_ai.ingestion.types import ParsedDocument
from trustdesk_ai.providers.base import EmbeddingProvider
from trustdesk_ai.rag.language import detect_language, tsv_config_for

log = logging.getLogger(__name__)

EMBED_BATCH = 32
StatusCallback = Callable[[str], Awaitable[None]]


class IndexingError(RuntimeError):
    """Indexing failed; the message is admin-safe."""


class EmbeddingIndexMismatchError(RuntimeError):
    """Configured embedding model differs from the tenant's active index; a re-embed job is required."""


@dataclass(frozen=True)
class IndexOutcome:
    document_id: UUID
    version_id: UUID | None
    unchanged: bool
    chunks: int
    embedded: int
    reused_embeddings: int


async def ensure_embedding_index(db: AsyncSession, tenant_id: UUID, embedder: EmbeddingProvider) -> EmbeddingIndex:
    active = (
        await db.execute(
            select(EmbeddingIndex).where(EmbeddingIndex.tenant_id == tenant_id, EmbeddingIndex.status == "active")
        )
    ).scalar_one_or_none()
    if active is None:
        active = EmbeddingIndex(
            tenant_id=tenant_id,
            provider=embedder.name,
            model=embedder.model,
            dimension=embedder.dimension,
            status="active",
            activated_at=datetime.now(UTC),
        )
        db.add(active)
        await db.flush()
        return active
    if (active.provider, active.model, active.dimension) != (embedder.name, embedder.model, embedder.dimension):
        raise EmbeddingIndexMismatchError(
            f"this organization's index uses {active.provider}/{active.model} ({active.dimension} dims) but the "
            f"service is configured for {embedder.name}/{embedder.model} ({embedder.dimension} dims). "
            "Start a re-embed from Sources, or restore the previous embedding settings."
        )
    return active


def document_hash(parsed: ParsedDocument) -> str:
    return content_hash("\n".join(f"{b.kind}:{b.level}:{b.text}" for b in parsed.blocks))


async def index_document(
    db: AsyncSession,
    *,
    document: Document,
    parsed: ParsedDocument,
    embedder: EmbeddingProvider,
    chunk_config: ChunkConfig,
    source_url: str | None,
    source_last_modified: datetime | None = None,
    raw_storage_key: str | None = None,
    byte_size: int | None = None,
    on_status: StatusCallback | None = None,
) -> IndexOutcome:
    """Runs inside the caller's tenant-scoped transaction (the worker commits per document)."""

    async def status(s: str) -> None:
        document.status = s
        if on_status:
            await on_status(s)

    digest = document_hash(parsed)
    if document.active_version_id is not None:
        active = await db.get(DocumentVersion, document.active_version_id)
        if active is not None and active.content_hash == digest:
            document.status, document.last_error = "indexed", None
            return IndexOutcome(document.id, active.id, True, 0, 0, 0)

    index = await ensure_embedding_index(db, document.tenant_id, embedder)
    next_no = (
        await db.execute(
            select(func.coalesce(func.max(DocumentVersion.version_no), 0)).where(
                DocumentVersion.document_id == document.id
            )
        )
    ).scalar_one() + 1
    language = parsed.language or detect_language(" ".join(b.text for b in parsed.blocks[:20]))
    version = DocumentVersion(
        tenant_id=document.tenant_id,
        document_id=document.id,
        version_no=next_no,
        content_hash=digest,
        state="building",
        title=parsed.title,
        source_last_modified=source_last_modified,
        byte_size=byte_size,
        raw_storage_key=raw_storage_key,
        metadata_=dict(parsed.metadata),
    )
    db.add(version)
    await db.flush()

    try:
        await status("chunking")
        drafts = chunk_blocks(parsed.blocks, chunk_config)
        if not drafts:
            raise ValueError("no indexable text found")
        chunks = [
            Chunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                document_version_id=version.id,
                ordinal=d.ordinal,
                content=d.content,
                token_count=d.token_count,
                content_hash=d.content_hash,
                source_url=source_url,
                page_title=parsed.title or document.title,
                section=d.section,
                heading_path=list(d.heading_path),
                parent_section_id=d.parent_section_id,
                page_number=d.page_number,
                language=language,
                tsv_config=tsv_config_for(language),
            )
            for d in drafts
        ]
        db.add_all(chunks)
        await db.flush()

        await status("embedding")
        reusable = await _existing_embeddings(db, index.id, {c.content_hash for c in chunks})
        to_embed = [c for c in chunks if c.content_hash not in reusable]
        vectors: dict[UUID, list[float]] = {
            c.id: reusable[c.content_hash] for c in chunks if c.content_hash in reusable
        }
        for i in range(0, len(to_embed), EMBED_BATCH):
            batch = to_embed[i : i + EMBED_BATCH]
            embedded = await embedder.embed(
                [embedding_text(c.page_title, c.heading_path, c.content) for c in batch], "document"
            )
            vectors.update({c.id: v for c, v in zip(batch, embedded, strict=True)})
        db.add_all(
            ChunkEmbedding(
                chunk_id=c.id,
                embedding_index_id=index.id,
                tenant_id=document.tenant_id,
                dimension=index.dimension,
                embedding=vectors[c.id],
            )
            for c in chunks
        )
        await db.flush()
    except Exception as exc:
        # The caller rolls back this transaction (no partial version survives; the active one is untouched)
        # and records the message in a fresh transaction.
        raise IndexingError(_safe_error(exc)) from exc

    await activate_version(db, document, version)
    return IndexOutcome(document.id, version.id, False, len(chunks), len(to_embed), len(chunks) - len(to_embed))


async def activate_version(db: AsyncSession, document: Document, version: DocumentVersion) -> None:
    previous = document.active_version_id
    now = datetime.now(UTC)
    if previous is not None:
        await db.execute(update(DocumentVersion).where(DocumentVersion.id == previous).values(state="superseded"))
        # Superseded chunks are no longer retrievable; citations keep their evidence snapshots.
        await db.execute(delete(Chunk).where(Chunk.document_version_id == previous))
    version.state, version.activated_at = "active", now
    document.active_version_id = version.id
    document.status, document.last_error, document.updated_at = "indexed", None, now
    if version.title and not document.title:
        document.title = version.title
    await db.flush()


async def _existing_embeddings(db: AsyncSession, index_id: UUID, hashes: set[str]) -> dict[str, list[float]]:
    if not hashes:
        return {}
    rows = await db.execute(
        select(Chunk.content_hash, ChunkEmbedding.embedding)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .where(ChunkEmbedding.embedding_index_id == index_id, Chunk.content_hash.in_(hashes))
        .distinct(Chunk.content_hash)
    )
    return {h: list(map(float, e)) for h, e in rows}


def _safe_error(exc: Exception) -> str:
    """Admin-facing message: provider/parse errors are already sanitized; anything else is generic."""
    from trustdesk_ai.ingestion.parsers.files import UnsupportedFileError
    from trustdesk_ai.providers.base import ProviderError

    if isinstance(exc, (ProviderError, UnsupportedFileError, EmbeddingIndexMismatchError, ValueError)):
        return str(exc)[:500]
    log.exception("indexing failed")
    return "indexing failed due to an internal error (see service logs for the correlation ID)"
