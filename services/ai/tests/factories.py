from datetime import UTC, datetime
from uuid import UUID, uuid4

from trustdesk_ai.retrieval.types import Candidate

TENANT = UUID("00000000-0000-0000-0000-00000000000a")
OTHER_TENANT = UUID("00000000-0000-0000-0000-00000000000b")


def cand(
    content: str = "Acme Studio designs websites for small businesses.",
    *,
    tenant: UUID = TENANT,
    vector: float | None = 0.8,
    rerank: float | None = None,
    language: str | None = "en",
    updated: datetime | None = None,
    tags: tuple[str, ...] = (),
    chunk_id: UUID | None = None,
) -> Candidate:
    return Candidate(
        chunk_id=chunk_id or uuid4(),
        tenant_id=tenant,
        document_id=uuid4(),
        document_version_id=uuid4(),
        content=content,
        source_url="https://acme.example/services",
        page_title="Services",
        section="Web design",
        language=language,
        vector_score=vector,
        rerank_score=rerank,
        tags=tags,
        source_updated_at=updated or datetime.now(UTC),
    )
