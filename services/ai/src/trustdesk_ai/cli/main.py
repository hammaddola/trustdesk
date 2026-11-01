"""`trustdesk` command-line interface."""

from __future__ import annotations

import asyncio
import os

import typer

app = typer.Typer(no_args_is_help=True, help="TrustDesk operations")


@app.command("db-bootstrap")
def db_bootstrap() -> None:
    """Create the runtime DB role, run migrations, apply grants (uses DIRECT_DATABASE_URL)."""
    from trustdesk_ai.cli.db import bootstrap
    from trustdesk_ai.config.settings import get_settings

    get_settings()  # loads .env
    password = os.environ.get("TRUSTDESK_APP_DB_PASSWORD") or _env_file_value("TRUSTDESK_APP_DB_PASSWORD")
    if not password:
        typer.echo("Set TRUSTDESK_APP_DB_PASSWORD (the password DATABASE_URL uses for trustdesk_app).", err=True)
        raise typer.Exit(2)
    bootstrap(password)
    typer.echo("Database ready: role trustdesk_app, schema trustdesk, migrations at head.")


@app.command("db-start")
def db_start() -> None:
    """Start the local embedded PostgreSQL (data in ./data/pg) and point .env at it."""
    from trustdesk_ai.cli.localdb import start, write_env

    password = os.environ.get("TRUSTDESK_APP_DB_PASSWORD") or _env_file_value("TRUSTDESK_APP_DB_PASSWORD")
    if not password:
        typer.echo("Set TRUSTDESK_APP_DB_PASSWORD in .env first.", err=True)
        raise typer.Exit(2)
    host, port = start()
    write_env(host, port, password)
    typer.echo(f"Local PostgreSQL running on {host}:{port} (data in ./data/pg); .env updated.")


@app.command()
def migrate() -> None:
    """Run pending migrations (uses DIRECT_DATABASE_URL)."""
    from trustdesk_ai.cli.db import migrate as run

    run()
    typer.echo("Migrations at head.")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:  # noqa: S104
    """Run the API server."""
    import uvicorn

    if reload:
        uvicorn.run("trustdesk_ai.main:create_app", factory=True, host=host, port=port, reload=True, proxy_headers=True)
        return
    # loop="none": keep the selector event loop policy set in trustdesk_ai/__init__.py (needed on Windows).
    config = uvicorn.Config(
        "trustdesk_ai.main:create_app", factory=True, host=host, port=port, loop="none", proxy_headers=True
    )
    asyncio.run(uvicorn.Server(config).serve())


@app.command()
def up(port: int = 3100, rebuild: bool = False) -> None:
    """Run everything (database, API, worker, dashboard + widget) behind one port."""
    from trustdesk_ai.cli.up import run

    run(port, rebuild)


@app.command()
def worker() -> None:
    """Run the background indexing worker."""
    from trustdesk_ai.ingestion.worker import run_forever
    from trustdesk_ai.main import configure_logging

    configure_logging()
    asyncio.run(run_forever())


@app.command()
def doctor() -> None:
    """Check configuration, database, pgvector and providers; print plain-language fixes."""
    from trustdesk_ai.cli.doctor import run_doctor

    raise typer.Exit(asyncio.run(run_doctor()))


@app.command()
def reembed() -> None:
    """Re-embed all organizations with the configured embedding model (old index serves until the switch)."""
    from trustdesk_ai.cli.reembed import reembed_all
    from trustdesk_ai.main import configure_logging

    configure_logging()
    asyncio.run(reembed_all())


@app.command("seed-demo")
def seed_demo() -> None:
    """Create the fictional 'Acme Studio' DEMO organization with sample content (development only)."""
    from trustdesk_ai.cli.seed import seed

    asyncio.run(seed())


def _env_file_value(name: str) -> str | None:
    from trustdesk_ai.config.settings import _REPO_ROOT_ENV

    for path in (_REPO_ROOT_ENV,):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].split("#", 1)[0].strip() or None
    return None


if __name__ == "__main__":
    app()
