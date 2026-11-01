"""`trustdesk reembed`: move every organization to the currently configured embedding model.

For each tenant whose active index differs from EMBEDDING_PROVIDER/MODEL/DIMENSION: build a NEW index from the
chunks of active document versions, then switch it to active and retire the old one in one transaction. The old
index keeps serving answers until the switch (decision D5). Re-running is safe (a leftover building index is
replaced).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import typer
from sqlalchemy import create_engine, delete, pool, select, text, update

from trustdesk_ai.db.models import Chunk, ChunkEmbedding, Document, EmbeddingIndex
from trustdesk_ai.db.session import tenant_session
from trustdesk_ai.db.urls import migration_url
from trustdesk_ai.ingestion.chunker import embedding_text
from trustdesk_ai.providers.registry import embeddings

BATCH = 32


def _tenant_ids() -> list[UUID]:
    # Owner connection: listing all organizations is an operator task outside any tenant's RLS scope.
    engine = create_engine(migration_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        ids = [r[0] for r in conn.execute(text("SELECT id FROM trustdesk.tenants ORDER BY created_at"))]
    engine.dispose()
    return ids


async def reembed_tenant(tenant_id: UUID) -> str:
    embedder = embeddings()
    want = (embedder.name, embedder.model, embedder.dimension)
    async with tenant_session(tenant_id) as db:
        active = (
            await db.execute(select(EmbeddingIndex).where(EmbeddingIndex.status == "active"))
        ).scalar_one_or_none()
        if active is not None and (active.provider, active.model, active.dimension) == want:
            return "already up to date"
        await db.execute(delete(EmbeddingIndex).where(EmbeddingIndex.status == "building"))
        new = EmbeddingIndex(tenant_id=tenant_id, provider=want[0], model=want[1], dimension=want[2], status="building")
        db.add(new)
        await db.flush()
        new_id = new.id
        rows = (
            await db.execute(
                select(Chunk.id, Chunk.page_title, Chunk.heading_path, Chunk.content).join(
                    Document,
                    (Document.id == Chunk.document_id) & (Document.active_version_id == Chunk.document_version_id),
                )
            )
        ).all()

    for i in range(0, len(rows), BATCH):  # one transaction per batch keeps transactions short
        batch = rows[i : i + BATCH]
        vectors = await embedder.embed(
            [embedding_text(r.page_title, r.heading_path, r.content) for r in batch], "document"
        )
        async with tenant_session(tenant_id) as db:
            db.add_all(
                ChunkEmbedding(
                    chunk_id=r.id, embedding_index_id=new_id, tenant_id=tenant_id, dimension=want[2], embedding=v
                )
                for r, v in zip(batch, vectors, strict=True)
            )

    async with tenant_session(tenant_id) as db:  # atomic switch
        await db.execute(update(EmbeddingIndex).where(EmbeddingIndex.status == "active").values(status="retired"))
        await db.execute(
            update(EmbeddingIndex)
            .where(EmbeddingIndex.id == new_id)
            .values(status="active", activated_at=datetime.now(UTC))
        )
        await db.execute(
            delete(ChunkEmbedding).where(
                ChunkEmbedding.embedding_index_id.in_(
                    select(EmbeddingIndex.id).where(EmbeddingIndex.status == "retired")
                )
            )
        )
    return f"re-embedded {len(rows)} chunks with {want[0]}/{want[1]} ({want[2]} dims)"


async def reembed_all() -> None:
    for tid in _tenant_ids():
        typer.echo(f"{tid}: {await reembed_tenant(tid)}")
