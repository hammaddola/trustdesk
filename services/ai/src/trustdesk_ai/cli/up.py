"""`trustdesk up`: run the whole project locally behind ONE public port.

Starts: local PostgreSQL (if DATABASE_URL points at it), the AI API on 127.0.0.1:8000 (internal only),
the indexing worker, and the Next.js app on PORT (default 3100), which serves the dashboard, the widget
script (/trustdesk.js), a demo page (/demo) and proxies /v1/* to the API. Ctrl+C stops everything.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

import typer

from trustdesk_ai.config.settings import _REPO_ROOT_ENV

ROOT = _REPO_ROOT_ENV.parent
ADMIN = ROOT / "apps" / "admin"
WIDGET = ROOT / "apps" / "widget"
API_PORT = 8000


def _wait(url: str, timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def _npx() -> str:
    exe = shutil.which("npx.cmd" if sys.platform == "win32" else "npx")
    if not exe:
        raise typer.BadParameter("Node.js (npx) is required: https://nodejs.org")
    return exe


def run(port: int, rebuild: bool) -> None:
    from trustdesk_ai.cli.main import _env_file_value

    if "127.0.0.1" in (_env_file_value("DATABASE_URL") or "") or "localhost" in (_env_file_value("DATABASE_URL") or ""):
        from trustdesk_ai.cli.localdb import start, write_env

        password = _env_file_value("TRUSTDESK_APP_DB_PASSWORD") or ""
        host, db_port = start()
        write_env(host, db_port, password)
        typer.echo(f"[db]     local PostgreSQL on {host}:{db_port}")

    npx = _npx()
    if rebuild or not (WIDGET / "dist" / "trustdesk.js").exists():
        typer.echo("[build]  widget…")
        subprocess.run([npx, "vite", "build"], cwd=WIDGET, check=True)
    if rebuild or not (ADMIN / ".next" / "BUILD_ID").exists():
        typer.echo("[build]  dashboard…")
        subprocess.run(["node", "scripts/copy-widget.mjs"], cwd=ADMIN, check=True)
        build_env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
        subprocess.run([npx, "next", "build"], cwd=ADMIN, check=True, env=build_env)
    else:
        subprocess.run(["node", "scripts/copy-widget.mjs"], cwd=ADMIN, check=True)

    exe = [sys.executable, "-m", "trustdesk_ai.cli.main"]
    procs: list[tuple[str, subprocess.Popen[bytes]]] = []
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)  # Windows-only constant
    try:
        procs.append(
            (
                "api",
                subprocess.Popen(
                    [*exe, "serve", "--host", "127.0.0.1", "--port", str(API_PORT)],
                    cwd=ROOT / "services" / "ai",
                    creationflags=flags,
                ),
            )
        )
        if not _wait(f"http://127.0.0.1:{API_PORT}/readyz"):
            typer.echo("API did not become ready; see the log above (`trustdesk doctor` helps).", err=True)
            raise typer.Exit(1)
        procs.append(
            (
                "worker",
                subprocess.Popen(
                    [*exe, "worker"],
                    cwd=ROOT / "services" / "ai",
                    creationflags=flags,
                ),
            )
        )
        env = {
            **os.environ,
            "NEXT_TELEMETRY_DISABLED": "1",
            "AI_SERVICE_URL": f"http://127.0.0.1:{API_PORT}",
            "WIDGET_CDN_URL": f"http://localhost:{port}",
            "PUBLIC_AI_SERVICE_URL": f"http://localhost:{port}",
        }
        procs.append(
            (
                "web",
                subprocess.Popen(
                    [npx, "next", "start", "-p", str(port)],
                    cwd=ADMIN,
                    env=env,
                    creationflags=flags,
                ),
            )
        )
        if not _wait(f"http://localhost:{port}/login"):
            typer.echo(f"Web app did not start on port {port} (is the port in use?).", err=True)
            raise typer.Exit(1)
        typer.echo(
            f"\nTrustDesk is running on ONE port: http://localhost:{port}\n"
            f"  Dashboard     http://localhost:{port}\n"
            f"  Widget demo   http://localhost:{port}/demo\n"
            f"  Widget script http://localhost:{port}/trustdesk.js\n"
            f"  API           http://localhost:{port}/v1/...\n"
            "Press Ctrl+C to stop.\n"
        )
        while all(p.poll() is None for _, p in procs):
            time.sleep(1)
        dead = [name for name, p in procs if p.poll() is not None]
        typer.echo(f"Stopped because {', '.join(dead)} exited.", err=True)
    except KeyboardInterrupt:
        typer.echo("\nStopping…")
    finally:
        for _, p in reversed(procs):
            if p.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
                else:
                    p.send_signal(signal.SIGTERM)
        for _, p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
