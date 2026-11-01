"""Schema, RLS isolation, ingestion/versioning, hybrid retrieval, chat streaming, leads — on real Postgres."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select, text

from tests.integration.conftest import TestTenant, upload_source
from trustdesk_ai.db.models import Base, Chunk, ChunkEmbedding, Document, DocumentVersion, Lead, Message
from trustdesk_ai.db.session import get_engine, global_session, tenant_session
from trustdesk_ai.ingestion.chunker import ChunkConfig
from trustdesk_ai.ingestion.pipeline import IndexingError, index_document
from trustdesk_ai.ingestion.types import Block, ParsedDocument
from trustdesk_ai.providers.registry import embeddings
from trustdesk_ai.retrieval.hybrid import RetrievalConfig, hybrid_retrieve

pytestmark = pytest.mark.integration


def doc(*paras: str, title: str = "Pricing") -> ParsedDocument:
    return ParsedDocument(
        blocks=[Block("heading", title, level=1), *[Block("paragraph", p) for p in paras]], title=title, language="en"
    )


async def ingest(tenant_id, parsed: ParsedDocument, url: str = "https://www.example.com/pricing"):
    source_id = await upload_source(tenant_id)
    async with tenant_session(tenant_id) as db:
        d = Document(tenant_id=tenant_id, source_id=source_id, source_type="web_page", canonical_url=url)
        db.add(d)
        await db.flush()
        outcome = await index_document(
            db, document=d, parsed=parsed, embedder=embeddings(), chunk_config=ChunkConfig(), source_url=url
        )
        return d.id, outcome


async def test_orm_matches_migrated_schema():
    async with get_engine().connect() as conn:

        def columns(sync_conn):
            insp = inspect(sync_conn)
            return {
                t: {c["name"] for c in insp.get_columns(t, schema="trustdesk")}
                for t in insp.get_table_names(schema="trustdesk")
            }

        db_cols = await conn.run_sync(columns)
    for table in Base.metadata.sorted_tables:
        assert table.name in db_cols, f"table {table.name} missing in database"
        missing = {c.name for c in table.columns} - db_cols[table.name]
        assert not missing, f"{table.name}: ORM columns not in DB: {missing}"


async def test_runtime_role_is_subject_to_rls():
    async with global_session() as db:
        row = (await db.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))).one()
    assert not row.rolsuper and not row.rolbypassrls


async def test_cross_tenant_isolation(tenants: tuple[TestTenant, TestTenant]):
    a, b = tenants
    await ingest(a.id, doc("Tenant A secret pricing is 111 dollars."))
    # Without tenant context nothing tenant-owned is visible (fail closed).
    async with global_session() as db:
        assert (await db.execute(select(func.count()).select_from(Chunk))).scalar_one() == 0
        assert (await db.execute(select(func.count()).select_from(Document))).scalar_one() == 0
    # Tenant B cannot see, update or delete tenant A's rows even with explicit IDs.
    async with tenant_session(b.id) as db:
        assert (await db.execute(select(func.count()).select_from(Chunk))).scalar_one() == 0
        upd = await db.execute(text("UPDATE documents SET title = 'pwned' WHERE tenant_id = :a"), {"a": a.id})
        assert upd.rowcount == 0
    # Tenant B cannot insert rows claiming tenant A.
    async with tenant_session(b.id) as db:
        with pytest.raises(Exception, match="row-level security"):
            await db.execute(text("INSERT INTO sources (tenant_id, kind) VALUES (:a, 'upload')"), {"a": a.id})


async def test_versioning_unchanged_skip_and_atomic_activation(tenants):
    a, _ = tenants
    doc_id, first = await ingest(a.id, doc("The Starter package costs $1,500."))
    assert not first.unchanged and first.chunks >= 1
    async with tenant_session(a.id) as db:
        d = await db.get(Document, doc_id)
        same = await index_document(
            db,
            document=d,
            parsed=doc("The Starter package costs $1,500."),
            embedder=embeddings(),
            chunk_config=ChunkConfig(),
            source_url=d.canonical_url,
        )
        assert same.unchanged  # no new version, no embedding cost
        changed = await index_document(
            db,
            document=d,
            parsed=doc("The Starter package costs $1,800."),
            embedder=embeddings(),
            chunk_config=ChunkConfig(),
            source_url=d.canonical_url,
        )
        assert not changed.unchanged
        versions = (
            await db.execute(
                select(DocumentVersion.version_no, DocumentVersion.state)
                .where(DocumentVersion.document_id == doc_id)
                .order_by(DocumentVersion.version_no)
            )
        ).all()
        assert [tuple(v) for v in versions] == [(1, "superseded"), (2, "active")]
        texts = (await db.execute(select(Chunk.content).where(Chunk.document_id == doc_id))).scalars().all()
        assert all("1,800" in t for t in texts)  # superseded chunks are no longer retrievable


async def test_failed_reindex_keeps_previous_version(tenants):
    a, _ = tenants
    doc_id, _ = await ingest(a.id, doc("Office hours are Monday to Friday."))

    class Broken:
        name, model, dimension = "mock", "mock-bow-v1", 1024

        async def embed(self, texts, kind):
            raise RuntimeError("provider down")

    with pytest.raises(IndexingError):
        async with tenant_session(a.id) as db:
            d = await db.get(Document, doc_id)
            await index_document(
                db,
                document=d,
                parsed=doc("Office hours changed to weekends."),
                embedder=Broken(),
                chunk_config=ChunkConfig(),
                source_url=d.canonical_url,
            )
    async with tenant_session(a.id) as db:
        texts = (await db.execute(select(Chunk.content).where(Chunk.document_id == doc_id))).scalars().all()
        assert texts and all("Monday to Friday" in t for t in texts)


async def test_hybrid_retrieval_vector_fts_and_isolation(tenants):
    a, b = tenants
    await ingest(a.id, doc("The Starter package costs $1,500 and includes five pages."))
    await ingest(a.id, doc("Our office is open Monday to Friday."), url="https://www.example.com/faq")
    await ingest(b.id, doc("The Starter package from tenant B costs $9,999."))
    query = "How much is the Starter package?"
    [vector] = await embeddings().embed([query], "query")
    async with tenant_session(a.id) as db:
        idx = (await db.execute(text("SELECT id, dimension FROM embedding_indexes WHERE status='active'"))).one()
        result = await hybrid_retrieve(
            db,
            tenant_id=a.id,
            query=query,
            query_vector=vector,
            index_id=idx.id,
            dimension=idx.dimension,
            config=RetrievalConfig(),
        )
    assert result.vector and result.fulltext, "both retrievers should return candidates"
    assert "Starter" in result.fused[0].content
    assert all(c.tenant_id == a.id for c in result.fused)
    assert all("9,999" not in c.content for c in result.fused)


async def test_chat_stream_end_to_end_and_leads(tenants):
    from fastapi.testclient import TestClient

    from trustdesk_ai.main import create_app
    from trustdesk_ai.tenancy.public import clear_cache

    a, _ = tenants
    await ingest(a.id, doc("The Starter package costs $1,500 and includes five pages."))
    async with tenant_session(a.id) as db:
        await db.execute(
            text("UPDATE tenant_settings SET setup_completed_at = now() WHERE tenant_id = :t"), {"t": a.id}
        )
    clear_cache()
    client = TestClient(create_app())
    headers = {"Origin": a.origin}
    visitor = str(uuid4())
    with client.stream(
        "POST",
        f"/v1/public/{a.public_key}/chat/stream",
        headers=headers,
        json={"message": "How much does the Starter package cost?", "visitor_id": visitor},
    ) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "conversation_started" and events[-1] == "completed"
    assert "token" in events and "citation" in events and "confidence" in events
    completed = json.loads([ln for ln in body.splitlines() if ln.startswith("data: ")][-1][6:])
    assert completed["status"] == "answered"

    # Unsupported question -> handoff, no tokens
    with client.stream(
        "POST",
        f"/v1/public/{a.public_key}/chat/stream",
        headers=headers,
        json={"message": "Do you offer penetration testing?", "visitor_id": visitor},
    ) as r:
        body2 = "".join(r.iter_text())
    assert "event: handoff" in body2 and "event: token" not in body2

    # Lead: saved once even when submitted twice with the same idempotency key
    lead = {
        "channel": "email",
        "visitor_id": visitor,
        "conversation_id": completed["conversation_id"],
        "idempotency_key": "it-" + uuid4().hex,
        "email": "visitor@example.com",
        "consent": True,
        "message": "Please call me",
    }
    r1 = client.post(f"/v1/public/{a.public_key}/leads", headers=headers, json=lead)
    r2 = client.post(f"/v1/public/{a.public_key}/leads", headers=headers, json=lead)
    assert r1.status_code == r2.status_code == 201 and r1.json()["lead_id"] == r2.json()["lead_id"]
    async with tenant_session(a.id) as db:
        assert (await db.execute(select(func.count()).select_from(Lead))).scalar_one() == 1
        stored = (await db.execute(select(Lead))).scalar_one()
        assert stored.summary and "Starter" in stored.summary
        cited = await db.execute(select(func.count()).select_from(Message).where(Message.role == "assistant"))
        assert cited.scalar_one() == 2
        assert (await db.execute(select(func.count()).select_from(ChunkEmbedding))).scalar_one() >= 1
