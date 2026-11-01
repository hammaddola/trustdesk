"""Local embedded PostgreSQL 16 + pgvector (pip package `pgserver`): no Docker, no cloud account.

Data lives in <repo>/data/pg. `trustdesk db-start` starts the server (it keeps running in the background)
and writes DATABASE_URL / DIRECT_DATABASE_URL for the current port into <repo>/.env.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from trustdesk_ai.config.settings import _REPO_ROOT_ENV

DATA_DIR = _REPO_ROOT_ENV.parent / "data" / "pg"


def start() -> tuple[str, int]:
    try:
        import pgserver
    except ImportError as exc:
        raise RuntimeError("install the local database: pip install pgserver") from exc
    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    # cleanup_mode=None: leave the server running after this command exits.
    server = pgserver.get_server(str(DATA_DIR), cleanup_mode=None)
    parts = urlsplit(server.get_uri())
    return parts.hostname or "127.0.0.1", parts.port or 5432


def write_env(host: str, port: int, app_password: str, env_path: Path = _REPO_ROOT_ENV) -> None:
    text = env_path.read_text(encoding="utf-8")
    values = {
        # Local superuser has no password and listens on localhost only.
        "DIRECT_DATABASE_URL": f"postgresql://postgres@{host}:{port}/postgres",
        "DATABASE_URL": f"postgresql://trustdesk_app:{app_password}@{host}:{port}/postgres",
    }
    for key, value in values.items():
        pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
        text = pattern.sub(f"{key}={value}", text) if pattern.search(text) else text + f"\n{key}={value}\n"
    env_path.write_text(text, encoding="utf-8")
