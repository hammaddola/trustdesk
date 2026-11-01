"""Admin: knowledge sources and documents."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update

from trustdesk_ai.api.deps import AdminPrincipal, TenantDB
from trustdesk_ai.audit import audit
from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.models import Chunk, Document, DocumentVersion, IndexingJob, Source, TenantSettings
from trustdesk_ai.ingestion.parsers.files import UnsupportedFileError, sniff_file_type
from trustdesk_ai.ingestion.worker import storage
from trustdesk_ai.security.ssrf import BlockedURLError, validate_url

router = APIRouter(prefix="/v1/admin", tags=["admin-sources"])

ALLOWED_TAGS = frozenset({"case-study", "founder", "pricing", "faq"})


def _check_tags(tags: list[str]) -> list[str]:
    bad = [t for t in tags if t not in ALLOWED_TAGS]
    if bad:
        raise ValueError(f"unknown tags {bad}; allowed: {sorted(ALLOWED_TAGS)}")
    return sorted(set(tags))


class SourceIn(BaseModel):
    kind: Literal["website", "sitemap"]
    url: str = Field(min_length=4, max_length=2048)
    max_pages: int = Field(default=200, ge=1, le=2000)
    include_patterns: list[str] = Field(default_factory=list, max_length=20)
    exclude_patterns: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=4)

    _tags = field_validator("tags")(classmethod(lambda cls, v: _check_tags(v)))


class JobOut(BaseModel):
    id: UUID
    kind: str
    status: str
    progress: dict[str, int]
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class SourceOut(BaseModel):
    id: UUID
    kind: str
    root_url: str | None
    title: str | None = None  # first document's title (useful for uploads, which have no URL)
    enabled: bool
    tags: list[str]
    max_pages: int
    last_crawled_at: datetime | None
    created_at: datetime
    document_count: int
    indexed_count: int
    failed_count: int
    latest_job: JobOut | None


def _job_out(j: IndexingJob | None) -> JobOut | None:
    if j is None:
        return None
    return JobOut(
        id=j.id,
        kind=j.kind,
        status=j.status,
        progress={k: int(v) for k, v in (j.progress or {}).items()},
        error_message=j.error_message,
        created_at=j.created_at,
        finished_at=j.finished_at,
    )


async def _enqueue(db: TenantDB, tenant_id: UUID, source_id: UUID, kind: str, document_id: UUID | None = None) -> None:
    active = (
        await db.execute(
            select(func.count()).where(
                IndexingJob.source_id == source_id,
                IndexingJob.status.notin_(["indexed", "failed"]),
                IndexingJob.document_id.is_(None) if document_id is None else IndexingJob.document_id == document_id,
            )
        )
    ).scalar_one()
    if active:
        raise HTTPException(409, "this source is already being indexed")
    db.add(IndexingJob(tenant_id=tenant_id, source_id=source_id, document_id=document_id, kind=kind))


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(principal: AdminPrincipal, db: TenantDB) -> list[SourceOut]:
    sources = (await db.execute(select(Source).order_by(Source.created_at.desc()))).scalars().all()
    counts = {
        (sid, status): n
        for sid, status, n in await db.execute(
            select(Document.source_id, Document.status, func.count()).group_by(Document.source_id, Document.status)
        )
    }
    titles: dict[UUID, str] = {}
    for sid, title in await db.execute(
        select(Document.source_id, Document.title).where(Document.title.is_not(None)).order_by(Document.created_at)
    ):
        if title:
            titles.setdefault(sid, title)
    latest = {}
    for job in (
        await db.execute(
            select(IndexingJob)
            .distinct(IndexingJob.source_id)
            .order_by(IndexingJob.source_id, IndexingJob.created_at.desc())
        )
    ).scalars():
        latest[job.source_id] = job
    out = []
    for s in sources:
        per = {st: n for (sid, st), n in counts.items() if sid == s.id}
        out.append(
            SourceOut(
                id=s.id,
                kind=s.kind,
                root_url=s.root_url,
                title=titles.get(s.id),
                enabled=s.enabled,
                tags=list(s.tags),
                max_pages=s.max_pages,
                last_crawled_at=s.last_crawled_at,
                created_at=s.created_at,
                document_count=sum(per.values()),
                indexed_count=per.get("indexed", 0),
                failed_count=per.get("failed", 0),
                latest_job=_job_out(latest.get(s.id)),
            )
        )
    return out


@router.post("/sources", response_model=SourceOut, status_code=201)
async def add_source(body: SourceIn, principal: AdminPrincipal, db: TenantDB, request: Request) -> SourceOut:
    settings = await db.get(TenantSettings, principal.tenant_id)
    try:
        checked = validate_url(body.url, settings.allowed_domains if settings else [])
    except BlockedURLError as exc:
        raise HTTPException(422, f"{exc}. Add the domain in Settings > Website domains first.") from exc
    source = Source(
        tenant_id=principal.tenant_id,
        kind=body.kind,
        root_url=checked.url,
        max_pages=body.max_pages,
        include_patterns=body.include_patterns,
        exclude_patterns=body.exclude_patterns,
        tags=body.tags,
        created_by=principal.user_id,
    )
    db.add(source)
    await db.flush()
    await _enqueue(db, principal.tenant_id, source.id, "crawl")
    await audit(
        principal.tenant_id,
        principal.user_id,
        "source.created",
        target_type="source",
        target_id=source.id,
        request=request,
    )
    await db.refresh(source)
    return SourceOut(
        id=source.id,
        kind=source.kind,
        root_url=source.root_url,
        enabled=True,
        tags=list(source.tags),
        max_pages=source.max_pages,
        last_crawled_at=None,
        created_at=source.created_at,
        document_count=0,
        indexed_count=0,
        failed_count=0,
        latest_job=None,
    )


@router.post("/sources/upload", status_code=201)
async def upload(
    principal: AdminPrincipal, db: TenantDB, request: Request, file: UploadFile = File(...), tags: str = Form("")
) -> dict[str, str]:
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"file is larger than {limit // (1024 * 1024)} MB")
    try:
        kind = sniff_file_type(file.filename or "", data)
        tag_list = _check_tags([t for t in tags.split(",") if t])
    except (UnsupportedFileError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    key = f"{principal.tenant_id}/{secrets.token_hex(16)}.{kind}"  # never use the client's filename as a path
    await storage().put(key, data)
    title = (file.filename or "document").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]
    source = Source(tenant_id=principal.tenant_id, kind="upload", tags=tag_list, created_by=principal.user_id)
    db.add(source)
    await db.flush()
    document = Document(
        tenant_id=principal.tenant_id,
        source_id=source.id,
        source_type=kind,
        storage_key=key,
        title=title,
        tags=tag_list,
    )
    db.add(document)
    await db.flush()
    await _enqueue(db, principal.tenant_id, source.id, "ingest_file", document.id)
    await audit(
        principal.tenant_id,
        principal.user_id,
        "source.uploaded",
        target_type="document",
        target_id=document.id,
        request=request,
        bytes=len(data),
        kind=kind,
    )
    return {"source_id": str(source.id), "document_id": str(document.id)}


class DocumentOut(BaseModel):
    id: UUID
    title: str | None
    url: str | None
    source_type: str
    status: str
    enabled: bool
    tags: list[str]
    last_error: str | None
    version_no: int | None
    version_indexed_at: datetime | None
    source_last_modified: datetime | None
    chunk_count: int
    updated_at: datetime


class SourceDetail(BaseModel):
    source: SourceOut
    documents: list[DocumentOut]
    jobs: list[JobOut]


@router.get("/sources/{source_id}", response_model=SourceDetail)
async def source_detail(source_id: UUID, principal: AdminPrincipal, db: TenantDB) -> SourceDetail:
    summary = next((s for s in await list_sources(principal, db) if s.id == source_id), None)
    if summary is None:
        raise HTTPException(404, "source not found")
    rows = await db.execute(
        select(Document, DocumentVersion, func.count(Chunk.id))
        .outerjoin(DocumentVersion, DocumentVersion.id == Document.active_version_id)
        .outerjoin(Chunk, Chunk.document_version_id == Document.active_version_id)
        .where(Document.source_id == source_id)
        .group_by(Document.id, DocumentVersion.id)
        .order_by(Document.canonical_url, Document.title)
    )
    documents = [
        DocumentOut(
            id=d.id,
            title=d.title,
            url=d.canonical_url,
            source_type=d.source_type,
            status=d.status,
            enabled=d.enabled,
            tags=list(d.tags),
            last_error=d.last_error,
            version_no=v.version_no if v else None,
            version_indexed_at=v.activated_at if v else None,
            source_last_modified=v.source_last_modified if v else None,
            chunk_count=n,
            updated_at=d.updated_at,
        )
        for d, v, n in rows
    ]
    jobs = (
        (
            await db.execute(
                select(IndexingJob)
                .where(IndexingJob.source_id == source_id)
                .order_by(IndexingJob.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return SourceDetail(source=summary, documents=documents, jobs=[j for j in map(_job_out, jobs) if j])


class SourcePatch(BaseModel):
    enabled: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=4)

    _tags = field_validator("tags")(classmethod(lambda cls, v: v if v is None else _check_tags(v)))


@router.patch("/sources/{source_id}", status_code=204)
async def update_source(
    source_id: UUID, body: SourcePatch, principal: AdminPrincipal, db: TenantDB, request: Request
) -> None:
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    if body.enabled is not None:
        source.enabled = body.enabled
    if body.tags is not None:
        source.tags = body.tags
        await db.execute(update(Document).where(Document.source_id == source_id).values(tags=body.tags))
    await audit(
        principal.tenant_id,
        principal.user_id,
        "source.updated",
        target_type="source",
        target_id=source_id,
        request=request,
        **body.model_dump(exclude_none=True),
    )


@router.post("/sources/{source_id}/reindex", status_code=202)
async def reindex(source_id: UUID, principal: AdminPrincipal, db: TenantDB, request: Request) -> None:
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    if source.kind == "upload":
        doc = (await db.execute(select(Document).where(Document.source_id == source_id))).scalar_one()
        await _enqueue(db, principal.tenant_id, source_id, "ingest_file", doc.id)
    else:
        await _enqueue(db, principal.tenant_id, source_id, "crawl")
    await audit(
        principal.tenant_id,
        principal.user_id,
        "source.reindex",
        target_type="source",
        target_id=source_id,
        request=request,
    )


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: UUID, principal: AdminPrincipal, db: TenantDB, request: Request) -> None:
    keys = [
        k
        for (k,) in await db.execute(
            select(Document.storage_key).where(Document.source_id == source_id, Document.storage_key.is_not(None))
        )
    ]
    result = await db.execute(delete(Source).where(Source.id == source_id))
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "source not found")
    for key in keys:
        if key:
            await storage().delete(key)
    await audit(
        principal.tenant_id,
        principal.user_id,
        "source.deleted",
        target_type="source",
        target_id=source_id,
        request=request,
    )


class DocumentPatch(BaseModel):
    enabled: bool


@router.patch("/documents/{document_id}", status_code=204)
async def update_document(
    document_id: UUID, body: DocumentPatch, principal: AdminPrincipal, db: TenantDB, request: Request
) -> None:
    result = await db.execute(update(Document).where(Document.id == document_id).values(enabled=body.enabled))
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(404, "document not found")
    await audit(
        principal.tenant_id,
        principal.user_id,
        "document.updated",
        target_type="document",
        target_id=document_id,
        request=request,
        enabled=body.enabled,
    )
