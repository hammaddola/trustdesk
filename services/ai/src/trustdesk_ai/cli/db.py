"""Database bootstrap: runtime role, migrations, privileges. Idempotent; safe to re-run."""

from __future__ import annotations

import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, pool, text

from trustdesk_ai.db.urls import migration_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

GRANTS = """
REVOKE ALL ON SCHEMA trustdesk FROM PUBLIC;
GRANT USAGE ON SCHEMA trustdesk TO trustdesk_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA trustdesk TO trustdesk_app;
REVOKE UPDATE, DELETE ON trustdesk.audit_logs FROM trustdesk_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA trustdesk TO trustdesk_app;
ALTER ROLE trustdesk_app SET search_path = trustdesk, public, extensions;
"""


def migrate() -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent.parent.parent / "database" / "migrations"))
    command.upgrade(cfg, "head")


def bootstrap(app_password: str) -> None:
    if len(app_password) < 16 or not re.fullmatch(r"[A-Za-z0-9_\-]+", app_password):
        raise ValueError("app DB password must be >=16 chars of [A-Za-z0-9_-]")
    engine = create_engine(migration_url(), poolclass=pool.NullPool)
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'trustdesk_app'")).scalar()
        # Password is validated above to a safe charset; CREATE ROLE cannot take bind parameters.
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            text(
                f"{verb} ROLE trustdesk_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                f"NOCREATEROLE PASSWORD '{app_password}'"
            )
        )
    migrate()
    with engine.begin() as conn:
        conn.execute(text(GRANTS))
    engine.dispose()
