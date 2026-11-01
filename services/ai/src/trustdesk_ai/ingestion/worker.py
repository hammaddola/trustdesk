"""Indexing worker: claims jobs with FOR UPDATE SKIP LOCKED and runs crawl / file ingestion.

Run with `trustdesk worker`. Each document is indexed in its own transaction, so one bad page fails only
that page. Errors shown to admins are sanitized.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update

from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.models import Document, IndexingJob, Source, TenantSettings
from trustdesk_ai.db.session import global_session, tenant_session
from trustdesk_ai.ingestion.chunker import ChunkConfig
from trustdesk_ai.ingestion.parsers.files import parse_docx, parse_pdf
from trustdesk_ai.ingestion.parsers.html import parse_html
from trustdesk_ai.ingestion.pipeline import IndexingError, _safe_error, index_document
from trustdesk_ai.ingestion.sitemap import discover_urls
from trustdesk_ai.providers import registry
from trustdesk_ai.providers.storage.local import LocalStorage
from trustdesk_ai.security.ssrf import BlockedURLError, safe_client, safe_fetch, validate_url

log = logging.getLogger(__name__)
WORKER_ID = f"{socket.gethostname()}-{id(object())}"
HTML_TYPES = ("text/html", "application/xhtml+xml")


def storage() -> LocalStorage:
    # shortcut: only local storage is wired here; S3 adapter is a P1 follow-up (docs/providers.md).
    return LocalStorage(get_settings().storage_local_dir)


async def _set_job(tenant_id: UUID, job_id: UUID, **values: Any) -> None:
    async with tenant_session(tenant_id) as db:
        await db.execute(update(IndexingJob).where(IndexingJob.id == job_id).values(**values))


async def claim_job() -> tuple[UUID, UUID] | None:
    async with global_session() as db:
        row = (await db.execute(text("SELECT job_id, tenant_id FROM claim_indexing_job(:w)"), {"w": WORKER_ID})).first()
    return (row.job_id, row.tenant_id) if row else None


async def run_job(job_id: UUID, tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as db:
        job = await db.get(IndexingJob, job_id)
        source = await db.get(Source, job.source_id) if job else None
        settings = await db.get(TenantSettings, tenant_id)
    if job is None or source is None or settings is None:
        return
    try:
        if job.kind == "ingest_file" and job.document_id:
            await _ingest_file(tenant_id, job_id, job.document_id)
        else:
            await _crawl(tenant_id, job_id, source, settings, job.document_id)
    except Exception as exc:
        await _set_job(
            tenant_id,
            job_id,
            status="failed",
            error_message=_safe_error(exc),
            error_code=type(exc).__name__,
            finished_at=datetime.now(UTC),
        )
        return
    async with tenant_session(tenant_id) as db:
        job = await db.get(IndexingJob, job_id)
        failed = int((job.progress or {}).get("failed", 0)) if job else 0
        ok = int((job.progress or {}).get("processed", 0)) if job else 0
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id == job_id)
            .values(
                status="failed" if failed and not ok else "indexed",
                finished_at=datetime.now(UTC),
                error_message=f"{failed} page(s) failed; see each document for details" if failed else None,
            )
        )
        await db.execute(update(Source).where(Source.id == source.id).values(last_crawled_at=datetime.now(UTC)))


async def _index_one(
    tenant_id: UUID, document_id: UUID, parsed: Any, url: str | None, last_modified: datetime | None, byte_size: int
) -> str:
    """Index one document in its own transaction; record failure in a fresh one.
    Returns "processed", "skipped_unchanged" or "failed" (the progress counter to increment)."""
    embedder = registry.embeddings()
    try:
        async with tenant_session(tenant_id) as db:
            document = await db.get(Document, document_id)
            if document is None:
                return "failed"
            if parsed.title and not document.title:
                document.title = parsed.title
            outcome = await index_document(
                db,
                document=document,
                parsed=parsed,
                embedder=embedder,
                chunk_config=ChunkConfig(),
                source_url=url,
                source_last_modified=last_modified,
                byte_size=byte_size,
            )
        return "skipped_unchanged" if outcome.unchanged else "processed"
    except Exception as exc:
        message = str(exc) if isinstance(exc, IndexingError) else _safe_error(exc)
        async with tenant_session(tenant_id) as db:
            document = await db.get(Document, document_id)
            if document is not None:
                document.last_error = message
                document.status = "indexed" if document.active_version_id else "failed"
        return "failed"


async def _ingest_file(tenant_id: UUID, job_id: UUID, document_id: UUID) -> None:
    async with tenant_session(tenant_id) as db:
        document = await db.get(Document, document_id)
        if document is None or not document.storage_key:
            raise IndexingError("uploaded file is missing")
        document.status = "parsing"
        key, kind = document.storage_key, document.source_type
    await _set_job(tenant_id, job_id, status="parsing")
    data = await storage().get(key)
    parsed = parse_pdf(data) if kind == "pdf" else parse_docx(data)
    await _set_job(tenant_id, job_id, status="embedding")
    result = await _index_one(tenant_id, document_id, parsed, None, None, len(data))
    await _set_job(
        tenant_id,
        job_id,
        progress={"found": 1, "processed": int(result != "failed"), "failed": int(result == "failed")},
    )


async def _upsert_page(tenant_id: UUID, source: Source, url: str) -> UUID:
    async with tenant_session(tenant_id) as db:
        existing = (
            await db.execute(select(Document).where(Document.tenant_id == tenant_id, Document.canonical_url == url))
        ).scalar_one_or_none()
        if existing:
            return existing.id
        doc = Document(
            tenant_id=tenant_id,
            source_id=source.id,
            source_type="web_page",
            canonical_url=url,
            tags=list(source.tags),
            status="crawling",
        )
        db.add(doc)
        await db.flush()
        return doc.id


async def _crawl(
    tenant_id: UUID, job_id: UUID, source: Source, settings: TenantSettings, only_document: UUID | None
) -> None:
    domains = list(settings.allowed_domains)
    if not source.root_url:
        raise IndexingError("source has no URL")
    validate_url(source.root_url, domains)
    if only_document:
        async with tenant_session(tenant_id) as db:
            doc = await db.get(Document, only_document)
            urls = [doc.canonical_url] if doc and doc.canonical_url else []
        follow_links = False
    else:
        sitemap = source.root_url if source.kind == "sitemap" else None
        urls = await discover_urls(source.root_url, domains, source.max_pages, sitemap_url=sitemap)
        follow_links = not urls and source.kind == "website"  # no sitemap: breadth-first link crawl
        urls = urls or [source.root_url]

    progress = {"found": len(urls), "processed": 0, "skipped_unchanged": 0, "failed": 0}
    queue, seen = deque(urls), set(urls)
    async with safe_client() as http:
        while queue and sum(progress[k] for k in ("processed", "skipped_unchanged", "failed")) < source.max_pages:
            url = queue.popleft()
            if source.exclude_patterns and any(p in url for p in source.exclude_patterns):
                continue
            if source.include_patterns and not any(p in url for p in source.include_patterns):
                continue
            await _set_job(tenant_id, job_id, status="crawling", progress=progress)
            try:
                page = await safe_fetch(url, domains, client=http)
            except BlockedURLError as exc:
                progress["failed"] += 1
                log.info("skipped %s: %s", url, exc)
                continue
            if page.status_code >= 400:
                progress["failed"] += 1
                continue
            if page.status_code != 200 or page.content_type not in HTML_TYPES:
                continue  # not a web page (image, PDF link, 204...): ignore
            parsed_page = parse_html(page.body, page.url)
            canonical = _canonical(parsed_page.canonical_url, page.url, domains)
            if follow_links:
                for link in parsed_page.links:
                    if link not in seen and len(seen) < source.max_pages:
                        try:
                            validate_url(link, domains)
                        except BlockedURLError:
                            continue
                        seen.add(link)
                        queue.append(link)
                progress["found"] = len(seen)
            document_id = await _upsert_page(tenant_id, source, canonical)
            await _set_job(tenant_id, job_id, status="embedding", progress=progress)
            modified = _parse_http_date(page.last_modified)
            result = await _index_one(tenant_id, document_id, parsed_page.document, canonical, modified, len(page.body))
            progress[result] += 1
            await asyncio.sleep(0.2)  # be polite to the customer's web server
    await _set_job(tenant_id, job_id, progress=progress)


def _canonical(declared: str | None, fetched: str, domains: list[str]) -> str:
    """Use the page's canonical URL only if it is itself an allowed URL; otherwise the fetched URL."""
    if declared:
        try:
            return validate_url(declared, domains).url
        except BlockedURLError:
            pass
    return fetched


def _parse_http_date(value: str | None) -> datetime | None:
    try:
        return parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None


async def run_forever(poll_seconds: float = 2.0) -> None:
    log.info("indexing worker %s started", WORKER_ID)
    while True:
        claimed = await claim_job()
        if claimed is None:
            await asyncio.sleep(poll_seconds)
            continue
        job_id, tenant_id = claimed
        await run_job(job_id, tenant_id)
