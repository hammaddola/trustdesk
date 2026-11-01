"""Vector and full-text retrieval over active, enabled content for one tenant.

Both queries filter `tenant_id` explicitly AND run under RLS (defence in depth), and only return chunks
of each document's *active* version from enabled documents in enabled sources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trustdesk_ai.config.settings import SUPPORTED_DIMENSIONS
from trustdesk_ai.rag.text import content_words
from trustdesk_ai.retrieval.types import Candidate

_CANDIDATE_COLUMNS = """
  c.id AS chunk_id, c.tenant_id, c.document_id, c.document_version_id, c.content, c.source_url,
  c.page_title, c.section, c.heading_path, c.language, d.tags,
  coalesce(dv.source_last_modified, dv.fetched_at) AS source_updated_at
"""

_ACTIVE_JOIN = """
  JOIN documents d ON d.id = c.document_id AND d.active_version_id = c.document_version_id AND d.enabled
  JOIN sources s ON s.id = d.source_id AND s.enabled
  JOIN document_versions dv ON dv.id = c.document_version_id
"""


@dataclass(frozen=True)
class MetadataFilter:
    tags_any: tuple[str, ...] = ()  # e.g. ("founder",) for Ask the Founder (P2)
    languages: tuple[str, ...] = ()

    def sql(self) -> str:
        clauses = []
        if self.tags_any:
            clauses.append("d.tags && CAST(:tags_any AS text[])")
        if self.languages:
            clauses.append("c.language = ANY(CAST(:languages AS text[]))")
        return "".join(f" AND {c}" for c in clauses)

    def params(self) -> dict[str, object]:
        return {"tags_any": list(self.tags_any), "languages": list(self.languages)}


def _row_to_candidate(row: object, vector_score: float | None = None, fts_score: float | None = None) -> Candidate:
    r = row._mapping  # type: ignore[attr-defined]
    return Candidate(
        chunk_id=r["chunk_id"],
        tenant_id=r["tenant_id"],
        document_id=r["document_id"],
        document_version_id=r["document_version_id"],
        content=r["content"],
        source_url=r["source_url"],
        page_title=r["page_title"],
        section=r["section"],
        heading_path=tuple(r["heading_path"] or ()),
        language=r["language"],
        tags=tuple(r["tags"] or ()),
        source_updated_at=r["source_updated_at"],
        vector_score=vector_score,
        fts_score=fts_score,
    )


async def vector_search(
    db: AsyncSession,
    tenant_id: UUID,
    index_id: UUID,
    dimension: int,
    query_vector: list[float],
    limit: int = 40,
    filters: MetadataFilter | None = None,
) -> list[Candidate]:
    if dimension not in SUPPORTED_DIMENSIONS or len(query_vector) != dimension:
        raise ValueError("query vector dimension does not match the index")
    f = filters or MetadataFilter()
    # Dimension is validated above, so interpolating it is safe; it must match the partial index expression.
    cast = f"vector({dimension})"
    sql = f"""
      SELECT {_CANDIDATE_COLUMNS},
             1 - (ce.embedding::{cast} <=> CAST(:q AS {cast})) AS score
      FROM chunk_embeddings ce
      JOIN chunks c ON c.id = ce.chunk_id
      {_ACTIVE_JOIN}
      WHERE ce.tenant_id = :tenant AND c.tenant_id = :tenant AND ce.embedding_index_id = :index
        AND ce.dimension = {dimension} {f.sql()}
      ORDER BY ce.embedding::{cast} <=> CAST(:q AS {cast})
      LIMIT :limit
    """  # noqa: S608 - only validated integers are interpolated
    await db.execute(text("SET LOCAL hnsw.ef_search = 100"))
    rows = await db.execute(
        text(sql),
        {"q": str(query_vector), "tenant": tenant_id, "index": index_id, "limit": limit, **f.params()},
    )
    return [_row_to_candidate(r, vector_score=max(0.0, float(r.score))) for r in rows]


_TERM = re.compile(r"[^\w]+", re.UNICODE)


def fts_terms(query: str, max_terms: int = 16) -> list[str]:
    terms = [_TERM.sub("", w) for w in content_words(query)]
    return list(dict.fromkeys(t for t in terms if t))[:max_terms]


async def fulltext_search(
    db: AsyncSession, tenant_id: UUID, query: str, limit: int = 40, filters: MetadataFilter | None = None
) -> list[Candidate]:
    terms = fts_terms(query)
    if not terms:
        return []
    f = filters or MetadataFilter()
    # OR semantics (any term) for recall; English chunks are stemmed, others use 'simple'. Terms are
    # stripped to word characters, so the tsquery string cannot carry operators from user input.
    or_query = " | ".join(terms)
    sql = f"""
      WITH q AS (SELECT to_tsquery('english', :tq) || to_tsquery('simple', :tq) AS query)
      SELECT {_CANDIDATE_COLUMNS}, ts_rank_cd(c.tsv, q.query) AS score
      FROM q, chunks c
      {_ACTIVE_JOIN}
      WHERE c.tenant_id = :tenant AND c.tsv @@ q.query {f.sql()}
      ORDER BY score DESC
      LIMIT :limit
    """  # noqa: S608 - static fragments only
    rows = await db.execute(text(sql), {"tq": or_query, "tenant": tenant_id, "limit": limit, **f.params()})
    return [_row_to_candidate(r, fts_score=float(r.score)) for r in rows]
