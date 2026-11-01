"""`trustdesk doctor`: configuration and environment checks with plain-language fixes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import typer
from sqlalchemy import text

OK, WARN, FAIL = "ok", "warn", "fail"


async def run_doctor() -> int:
    results: list[tuple[str, str, str]] = []

    async def check(name: str, fn: Callable[[], Awaitable[tuple[str, str]]]) -> None:
        try:
            status, detail = await fn()
        except Exception as exc:  # report, don't crash: doctor must always print a full list
            status, detail = FAIL, f"{type(exc).__name__}: {str(exc)[:300]}"
        results.append((name, status, detail))

    async def settings() -> tuple[str, str]:
        from trustdesk_ai.config.settings import get_settings

        s = get_settings()
        return (
            OK,
            f"mode={s.trustdesk_mode} env={s.trustdesk_env} llm={s.llm_provider} "
            f"embeddings={s.embedding_provider}({s.embedding_dimension}) reranker={s.reranker_provider}",
        )

    await check("configuration", settings)
    if results[-1][1] == FAIL:
        return _print(results)

    from trustdesk_ai.db.session import global_session

    async def database() -> tuple[str, str]:
        async with global_session() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT current_user, r.rolbypassrls, r.rolsuper, "
                        "(SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector "
                        "FROM pg_roles r WHERE r.rolname = current_user"
                    )
                )
            ).one()
            owner = (
                await db.execute(
                    text("SELECT tableowner FROM pg_tables WHERE schemaname = 'trustdesk' AND tablename = 'chunks'")
                )
            ).scalar_one_or_none()
        if owner is None:
            return FAIL, "schema 'trustdesk' not found. Fix: run `trustdesk db-bootstrap`."
        if row.rolsuper or row.rolbypassrls or row.current_user == owner:
            return FAIL, (
                f"DATABASE_URL connects as '{row.current_user}', which bypasses Row-Level Security. "
                "Fix: use the trustdesk_app role in DATABASE_URL."
            )
        if not row.vector:
            return FAIL, "pgvector is not installed. Fix: enable the 'vector' extension."
        return OK, f"connected as {row.current_user} (RLS enforced), pgvector {row.vector}"

    await check("database", database)

    async def dimensions() -> tuple[str, str]:
        from trustdesk_ai.config.settings import get_settings

        s = get_settings()
        async with global_session() as db:
            dims = (
                (
                    await db.execute(
                        text("SELECT provider || '/' || model || ':' || dimension FROM active_embedding_configs()")
                    )
                )
                .scalars()
                .all()
            )
        want = f"{s.embedding_provider}/{s.embedding_model}:{s.embedding_dimension}"
        if not dims:
            return OK, "no embedding index yet (created on first indexing)"
        if any(d != want for d in dims):
            return WARN, f"active indexes {sorted(set(dims))} differ from configured {want}; re-embed required"
        return OK, f"configured embeddings match the active index ({want})"

    await check("embedding index", dimensions)

    async def providers() -> tuple[str, str]:
        from trustdesk_ai.providers.registry import default_reranker, embeddings

        vec = (await embeddings().embed(["doctor check"], "query"))[0]
        reranker = default_reranker()
        if reranker is not None:
            await reranker.rerank("doctor check", ["doctor check passage"])
        return OK, f"embeddings returned {len(vec)} dims; reranker {'ok' if reranker else 'none (stricter gate)'}"

    await check("providers", providers)
    return _print(results)


def _print(results: list[tuple[str, str, str]]) -> int:
    icons = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}
    for name, status, detail in results:
        typer.echo(f"[{icons[status]}] {name}: {detail}")
    return 1 if any(s == FAIL for _, s, _ in results) else 0
