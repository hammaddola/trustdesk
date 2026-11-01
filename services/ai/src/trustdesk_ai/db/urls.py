"""Database URL normalization (psycopg3 driver for both sync and async engines)."""

from __future__ import annotations

import os

from trustdesk_ai.config.settings import get_settings


def _psycopg(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def runtime_url() -> str:
    return _psycopg(get_settings().database_url.get_secret_value())


def migration_url() -> str:
    # Alembic may run without the full app settings (e.g. in CI); read env directly first.
    url = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        s = get_settings()
        url = (s.direct_database_url or s.database_url).get_secret_value()
    return _psycopg(url)
