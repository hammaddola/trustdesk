# Contributing to TrustDesk

Thanks for helping! TrustDesk's promise is **no source, no answer**, so contributions are judged first on
evidence integrity, tenant isolation and privacy, then on features.

## Setup

Follow the quickstart in [README.md](README.md). Run everything with `trustdesk up`.

## Ground rules

- All business logic lives in `services/ai`. The dashboard and widget only render and call the API.
- API types are generated: change the Pydantic model, then `pnpm --filter @trustdesk/contracts generate`.
- Never trust model output: anything shown to visitors must pass `rag/verification.py`.
- Every tenant-owned table has `tenant_id` and an RLS policy; every query goes through `tenant_session`.
- No hard-coded organization data, credentials or real personal data (use the fictional Acme Studio demo).
- New external services must be optional adapters (see [docs/providers.md](docs/providers.md)) with a free
  local alternative or a clear "disabled" path. Ask before adding a paid dependency.
- Tests are required, and claims about tests must be true: run them and paste the result in the PR.

## Checks before a PR

```bash
cd services/ai && .venv/Scripts/python -m ruff check src tests && .venv/Scripts/python -m mypy src && .venv/Scripts/python -m pytest
TRUSTDESK_INTEGRATION=1 .venv/Scripts/python -m pytest tests/integration
corepack pnpm -r typecheck && corepack pnpm --filter @trustdesk/widget test && corepack pnpm --filter @trustdesk/widget build
```

## Commits and releases

Conventional commit messages (`feat:`, `fix:`, `docs:` …). Semantic versioning; every release updates
[CHANGELOG.md](CHANGELOG.md) and, for minor/major versions, includes upgrade notes.

By contributing you agree your work is licensed under Apache-2.0 and you follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
