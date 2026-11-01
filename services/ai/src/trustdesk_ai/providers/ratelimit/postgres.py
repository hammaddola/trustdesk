"""Fixed-window rate limiting in Postgres (default store; no Redis required)."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

from sqlalchemy import text

from trustdesk_ai.db.session import global_session


def bucket_key(*parts: str) -> str:
    """Hash identifiers (IPs, emails) so the table never stores them in clear text."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class PostgresRateLimitStore:
    name = "postgres"

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = int(time.time())
        window = datetime.fromtimestamp(now - now % window_seconds, UTC)
        async with global_session() as db:
            count = (
                await db.execute(
                    text("""
                  INSERT INTO rate_limit_buckets (bucket_key, window_start, count) VALUES (:k, :w, 1)
                  ON CONFLICT (bucket_key, window_start) DO UPDATE SET count = rate_limit_buckets.count + 1
                  RETURNING count
                """),
                    {"k": key, "w": window},
                )
            ).scalar_one()
            if count == 1 and now % 97 == 0:  # occasional cleanup, no scheduler needed
                await db.execute(text("DELETE FROM rate_limit_buckets WHERE window_start < now() - interval '1 day'"))
        return int(count) <= limit

    async def reserve(self, key: str, limit: int, window_seconds: int) -> tuple[bool, datetime]:
        """Like hit(), but also returns the window that was incremented so a refund can target it exactly."""
        now = int(time.time())
        window = datetime.fromtimestamp(now - now % window_seconds, UTC)
        async with global_session() as db:
            count = (
                await db.execute(
                    text(
                        "INSERT INTO rate_limit_buckets (bucket_key, window_start, count) VALUES (:k, :w, 1) "
                        "ON CONFLICT (bucket_key, window_start) DO UPDATE SET count = rate_limit_buckets.count + 1 "
                        "RETURNING count"
                    ),
                    {"k": key, "w": window},
                )
            ).scalar_one()
        return int(count) <= limit, window

    async def refund(self, key: str, window_start: datetime) -> None:
        """Give back one reserved hit in exactly the window it was taken from (never a later window)."""
        async with global_session() as db:
            await db.execute(
                text(
                    "UPDATE rate_limit_buckets SET count = GREATEST(count - 1, 0) "
                    "WHERE bucket_key = :k AND window_start = :w"
                ),
                {"k": key, "w": window_start},
            )

    async def count(self, key: str, window_seconds: int) -> int:
        """Current hits in this window, without adding one."""
        now = int(time.time())
        window = datetime.fromtimestamp(now - now % window_seconds, UTC)
        async with global_session() as db:
            value = (
                await db.execute(
                    text("SELECT count FROM rate_limit_buckets WHERE bucket_key = :k AND window_start = :w"),
                    {"k": key, "w": window},
                )
            ).scalar_one_or_none()
        return int(value or 0)
