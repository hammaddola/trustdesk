"""Resolve a widget's publishable key to a tenant and its public configuration (short in-process cache)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import text

from trustdesk_ai.db.models import TenantSettings
from trustdesk_ai.db.session import global_session, tenant_session

CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class PublicTenant:
    tenant_id: UUID
    organization: str
    allowed_origins: frozenset[str]
    greeting: str | None
    default_language: str
    enabled_languages: tuple[str, ...]
    widget_theme: dict[str, Any]
    handoff_channels: dict[str, Any]
    setup_complete: bool


_cache: dict[str, tuple[float, PublicTenant | None]] = {}


def normalize_origin(origin: str) -> str | None:
    """scheme://host[:port], lowercase, default ports dropped. None if not a valid http(s) origin."""
    parts = urlsplit(origin.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/"):
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    default = {"http": 80, "https": 443}[parts.scheme]
    host = parts.hostname.lower()
    return f"{parts.scheme}://{host}" + (f":{port}" if port and port != default else "")


def clear_cache() -> None:
    _cache.clear()


async def resolve(public_key: str) -> PublicTenant | None:
    if not public_key.startswith("td_pk_") or len(public_key) > 64:
        return None
    hit = _cache.get(public_key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    async with global_session() as db:
        row = (
            await db.execute(text("SELECT tenant_id, status FROM resolve_public_key(:k)"), {"k": public_key})
        ).first()
    tenant: PublicTenant | None = None
    if row is not None and row.status == "active":
        async with tenant_session(row.tenant_id) as db:
            s = await db.get(TenantSettings, row.tenant_id)
        if s is not None:
            tenant = PublicTenant(
                tenant_id=row.tenant_id,
                organization=s.organization_name,
                allowed_origins=frozenset(o for o in (normalize_origin(x) for x in s.allowed_origins) if o),
                greeting=s.greeting,
                default_language=s.default_language,
                enabled_languages=tuple(s.enabled_languages),
                widget_theme=dict(s.widget_theme),
                handoff_channels=dict(s.handoff_channels),
                setup_complete=s.setup_completed_at is not None,
            )
    _cache[public_key] = (time.monotonic() + CACHE_SECONDS, tenant)
    return tenant
