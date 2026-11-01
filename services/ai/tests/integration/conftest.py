"""Integration fixtures: real Postgres (DATABASE_URL as trustdesk_app), mock AI providers.

Run: TRUSTDESK_INTEGRATION=1 pytest tests/integration
Each test creates its own throwaway organizations and deletes them afterwards.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import pytest

if os.environ.get("TRUSTDESK_INTEGRATION") != "1":
    pytest.skip("set TRUSTDESK_INTEGRATION=1 to run integration tests", allow_module_level=True)

# Deterministic, free providers for integration tests (must be set before settings are first read).
os.environ.update(
    LLM_PROVIDER="mock",
    EMBEDDING_PROVIDER="mock",
    EMBEDDING_MODEL="mock-bow-v1",
    EMBEDDING_DIMENSION="1024",
    RERANKER_PROVIDER="mock",
    TRUSTDESK_ENV="test",
    EMAIL_PROVIDER="console",
    CAPTCHA_PROVIDER="none",
)

from sqlalchemy import text  # noqa: E402

from trustdesk_ai.config.settings import get_settings  # noqa: E402
from trustdesk_ai.db.models import Source, TenantSettings  # noqa: E402
from trustdesk_ai.db.session import get_engine, global_session, tenant_session  # noqa: E402
from trustdesk_ai.providers import registry  # noqa: E402

get_settings.cache_clear()
registry.embeddings.cache_clear()
registry.default_llm.cache_clear()
registry.default_reranker.cache_clear()


@dataclass
class TestTenant:
    __test__ = False

    id: UUID
    public_key: str
    origin: str


async def make_tenant(name: str) -> TestTenant:
    key = "td_pk_it_" + secrets.token_urlsafe(10)
    origin = "https://www.example.com"
    async with global_session() as db:
        tid = (
            await db.execute(
                text("SELECT create_tenant(:s, :n, :k, true)"), {"s": "it-" + secrets.token_hex(5), "n": name, "k": key}
            )
        ).scalar_one()
    async with tenant_session(tid) as db:
        db.add(
            TenantSettings(
                tenant_id=tid,
                organization_name=name,
                allowed_domains=["example.com"],
                allowed_origins=[origin],
                handoff_channels={"email": {"enabled": True}},
            )
        )
    return TestTenant(tid, key, origin)


async def drop_tenant(t: TestTenant) -> None:
    async with tenant_session(t.id) as db:
        await db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t.id})


@pytest.fixture
async def tenants() -> AsyncIterator[tuple[TestTenant, TestTenant]]:
    a, b = await make_tenant("IT Tenant A"), await make_tenant("IT Tenant B")
    try:
        yield a, b
    finally:
        await drop_tenant(a)
        await drop_tenant(b)
        await get_engine().dispose()


async def upload_source(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as db:
        source = Source(tenant_id=tenant_id, kind="upload")
        db.add(source)
        await db.flush()
        return source.id
