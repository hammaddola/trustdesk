"""Engine and tenant-scoped sessions.

Every transaction that touches tenant data must go through `tenant_session`, which sets
`app.tenant_id` transaction-locally so Postgres RLS applies (fail closed when unset).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from trustdesk_ai.db.urls import runtime_url


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(
        runtime_url(),
        pool_pre_ping=True,
        pool_size=10,
        # prepare_threshold=None keeps psycopg compatible with transaction-mode poolers (Supabase/pgbouncer).
        connect_args={"prepare_threshold": None, "options": "-c search_path=trustdesk,public,extensions"},
    )


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def global_session() -> AsyncIterator[AsyncSession]:
    """Session with no tenant context: only users/sessions and SECURITY DEFINER entry points are visible."""
    async with _sessionmaker()() as session, session.begin():
        yield session


@asynccontextmanager
async def tenant_session(tenant_id: UUID, user_id: UUID | None = None) -> AsyncIterator[AsyncSession]:
    async with _sessionmaker()() as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        if user_id is not None:
            await session.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
        yield session
