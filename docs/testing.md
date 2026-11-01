# Testing

Results below were produced on 2026-11-01 (Windows 11, Python 3.11.9, Node 24). Re-run before relying on them.

| Suite | Command | Result |
|---|---|---|
| Python unit + security (no DB) | `cd services/ai && .venv/Scripts/python -m pytest` | 118 passed, 1 skipped (integration) |
| Python integration (real Postgres + pgvector) | `TRUSTDESK_INTEGRATION=1 .venv/Scripts/python -m pytest tests/integration` | 7 passed |
| Python lint / types | `ruff check src tests` · `mypy src` (strict) | clean |
| Widget (Vitest + React Testing Library) | `pnpm --filter @trustdesk/widget test` | 9 passed |
| Widget bundle | `pnpm --filter @trustdesk/widget build` | 1 file, ~82 KB gzip (budget 90 KB) |
| TypeScript | `pnpm -r typecheck`; dashboard `next build` | clean |
| SDK (SSE parser) | `pnpm --filter @trustdesk/sdk test` | 2 passed |

## Coverage map (spec §12)

- **Unit:** chunk splitting, metadata preservation, hashing, RRF, answerability gate, citation verification,
  confidence, language detection, sentence streaming segmentation, parsers, API validation.
- **Integration:** schema ↔ ORM, RLS role check, cross-tenant isolation, versioning/unchanged skip/atomic
  activation, failed re-index keeps previous version, vector + full-text + hybrid retrieval, SSE end to end
  through HTTP, handoff → handoff event without tokens, lead persistence + idempotency.
- **Security:** SSRF (schemes, ports, IP literals incl. decimal/hex, metadata, IPv6, DNS rebinding, redirects,
  size), XXE, file sniffing, prompt injection, fabricated/foreign/inactive citations, invented prices,
  unauthenticated admin access, invalid CORS origins + preflight, request size, error echo.
- **Frontend:** widget streaming, citations, confidence tooltip, handoff form (consent, failure, success only
  after save), Escape + focus return, error/retry state, Shadow DOM mount, no global CSS, idempotent mount,
  invalid key leaves no DOM.

## Not yet covered

- Playwright end-to-end (real browser, mobile viewport, keyboard-only run) — planned.
- Dashboard component tests; auth flows are covered at the API level only.
- Load testing and an external security review.
