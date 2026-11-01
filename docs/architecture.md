# TrustDesk — Architecture & Execution Plan

Status: **Phase 1 in progress.** Anything not listed under *Progress* is a plan, not a feature.

### Progress (updated 2026-11-01)

| Area | State | Verified by |
|---|---|---|
| Schema, RLS, migrations, `db-bootstrap`; local embedded Postgres (`db-start`) | Implemented | integration tests on PostgreSQL 16 + pgvector |
| Auth (argon2id, sessions, RBAC), first-run setup | Implemented | API security tests; setup flow manual |
| Ingestion: SSRF-safe crawl, sitemaps, PDF/DOCX, chunking, versioning, worker | Implemented | unit, security, integration; live upload test |
| Hybrid retrieval, rerank, answerability, LangGraph, verification, confidence | Implemented | unit + integration |
| SSE streaming, public API, leads/handoff (email, WhatsApp, booking) | Implemented | integration + live run through one port |
| Usage metering, budgets, audit log, rate limiting (Postgres) | Implemented | partly tested |
| Widget (Shadow DOM, single script) | Implemented | 9 component tests; bundle check |
| Admin dashboard (all Phase 1 pages) | Implemented | type check, `next build`, every page rendered signed-in |
| One-port run (`trustdesk up`) | Implemented | live run |
| Docs, OSS files, CI workflow | Written | CI not yet run on GitHub (no remote) |
| Multi-step Setup Wizard (steps 2–7 as guided screens) | Partial — setup page + Overview checklist | — |
| Slack / Telegram / generic-webhook handoff, signed outgoing webhooks | Not started (tables exist) | — |
| `create-trustdesk`, `trustdesk eval/export/import`, Docker files | Not started | — |
| Re-embed (`trustdesk reembed`), Gemini via OpenAI-compatible adapters | Implemented | live run with Gemini |
| Playwright E2E, Langfuse tracing, S3 / Redis adapters | Not started | — |
| Phase 2 / 3 features | Not started (extension points in §6) | — |

## 1. Repository inspection (2026-10-31)

| Item | Finding | Consequence |
|---|---|---|
| Existing code | None — directory empty, not a git repo | Greenfield; nothing to preserve |
| Node.js | v24.22.1 | OK. pnpm is not installed → enable via `corepack enable` |
| Python | 3.11.9 | OK (target ≥3.11) |
| Docker | **Not installed** | `docker compose up`, Postgres integration tests and image builds cannot run locally until resolved |
| PostgreSQL | **Not installed** | Same — needs Docker, a native install, or an external Postgres (e.g. Supabase) URL |
| Company config | None supplied | Ship fictional **Acme Studio** demo tenant, clearly marked as demo data; real org data only via Setup Wizard |

## 2. Run modes

One schema, one codebase. `TRUSTDESK_MODE=simple|platform`.

- **simple** (default): one organization created by the Setup Wizard; tenant UI hidden; a single tenant row exists so the data model is identical; roles `owner`, `admin`.
- **platform**: many tenants, tenant switcher, per-tenant budgets.

`tenant_id` is on every tenant-owned row and RLS policies are installed in **both** modes, so switching modes needs no data migration.

## 3. Folder structure

Legend: **P1** = built in Phase 1, *P2/P3* = reserved, not created until that phase.

```
trustdesk/
├─ apps/
│  ├─ admin/                         P1  Next.js App Router dashboard (BFF only — no business logic)
│  │  ├─ src/app/(auth)/login/
│  │  ├─ src/app/(dashboard)/{overview,sources,conversations,leads,insights,playground,settings}/
│  │  ├─ src/app/setup/              P1  first-run Setup Wizard (7 steps)
│  │  ├─ src/app/api/                    route handlers proxying to AI service with the session token
│  │  ├─ src/lib/{api,session,auth}.ts
│  │  └─ src/components/
│  └─ widget/                        P1  Vite + React, Shadow DOM, single IIFE `trustdesk.js`
│     ├─ src/{loader.ts,mount.tsx,App.tsx}
│     ├─ src/components/{Launcher,Panel,MessageList,CitationChip,ConfidenceMeter,HandoffPanel}.tsx
│     ├─ src/lib/{sse.ts,i18n.ts,bidi.ts}
│     └─ src/styles/widget.css           compiled Tailwind, injected into the shadow root
├─ services/
│  └─ ai/                            P1  Python: FastAPI + LangGraph + SQLAlchemy
│     ├─ pyproject.toml                  extras: [local] (torch/sentence-transformers), [crawl]
│     ├─ alembic.ini                     script_location → ../../database/migrations
│     ├─ src/trustdesk_ai/
│     │  ├─ main.py                      app factory, middleware, routers
│     │  ├─ config/                      pydantic-settings; startup validation; trustdesk.config.json loader
│     │  ├─ db/                          engine, tenant-scoped session (SET LOCAL app.tenant_id), ORM models
│     │  ├─ auth/                        argon2 passwords, opaque DB sessions, RBAC dependencies
│     │  ├─ security/                    ssrf.py (safe resolver/transport), url_policy, uploads, headers, cors
│     │  ├─ providers/                   Protocols + one file per adapter + registry.py
│     │  │  ├─ llm/{ollama,openai,anthropic,openai_compat}.py
│     │  │  ├─ embeddings/{local,ollama,openai,cohere}.py
│     │  │  ├─ rerank/{local_cross_encoder,cohere,none}.py
│     │  │  ├─ email/{smtp,resend,console}.py
│     │  │  ├─ captcha/{turnstile,hcaptcha,none}.py
│     │  │  ├─ storage/{local,s3}.py
│     │  │  └─ ratelimit/{postgres,redis}.py
│     │  ├─ ingestion/                   sitemap, safe fetch, clean, parsers/{html,pdf,docx}, chunker, hashing, pipeline, worker
│     │  ├─ retrieval/                   vector, fulltext, filters, fusion (RRF), rerank, hybrid
│     │  ├─ rag/                         LangGraph: state, graph, nodes/*, answerability, confidence, language, verification
│     │  │  └─ prompts/                  versioned prompt files (e.g. answer.v1.md) + registry
│     │  ├─ handoff/                     channel plugins {email,whatsapp,booking,slack,telegram,webhook}, leads
│     │  ├─ webhooks/                    outbox, HMAC signer, dispatcher with backoff
│     │  ├─ usage/                       metering, price table, budgets
│     │  ├─ observability/               structlog JSON, correlation IDs, Langfuse tracing (PII-scrubbed)
│     │  ├─ cli/                         `trustdesk` CLI: doctor, ingest, eval, migrate, export, import
│     │  └─ api/{public,admin}/          thin routers; logic lives in the modules above
│     └─ tests/{unit,integration,security}/
├─ packages/
│  ├─ contracts/                     P1  @trustdesk/contracts — TS types GENERATED from FastAPI OpenAPI
│  ├─ sdk/                           P1  @trustdesk/sdk — typed REST + SSE client (used by widget and admin)
│  ├─ config/                        P1  @trustdesk/config — trustdesk.config JSON Schema + migrations (shared with Python)
│  ├─ ui/                            P1  design tokens (CSS variables) + shared primitives
│  ├─ tsconfig/  eslint-config/      P1
│  ├─ react/                         P2  <TrustDesk/> component
│  └─ (providers)                    — see decision D9
├─ cli/
│  └─ create-trustdesk/              P1  `npx create-trustdesk` generator (writes .env + trustdesk.config.json)
├─ database/
│  ├─ migrations/                    P1  Alembic revisions (single migration history)
│  ├─ init/                          P1  roles + extensions (runs once in the Postgres container)
│  └─ seed/acme-studio/              P1  fictional demo org content, marked DEMO
├─ infrastructure/
│  ├─ docker/{ai,admin,widget}.Dockerfile
│  └─ scripts/
├─ integrations/                     P2  wordpress/, shopify/  (P1 ships copy-paste guides in docs only)
├─ docs/                             P1  architecture, database, security, api, ingestion, deployment, testing, providers
├─ docs-site/                        P2
├─ evals/golden.jsonl                P3  (format reserved now)
├─ .github/{workflows/ci.yml,ISSUE_TEMPLATE/,pull_request_template.md}
├─ docker-compose.yml                    profiles: default (db, ai, admin, widget), `local` (+ollama)
├─ trustdesk.config.example.json
├─ .env.example
├─ pnpm-workspace.yaml  turbo.json  package.json
└─ README.md LICENSE CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md
```

Dependency direction (no cycles): `apps/* → packages/sdk → packages/contracts`; `apps/* → packages/ui`;
`cli/create-trustdesk → packages/config`. Python never imports TS; the shared contracts are the OpenAPI
document (generated from Pydantic) and the config JSON Schema.

## 4. Key decisions

**D1 — The Python service owns all business logic.** Ingestion, retrieval, RAG, auth, leads, usage and
settings live in `services/ai`. The Next.js admin is a backend-for-frontend: it renders UI and forwards
requests with the user's session. This is how we satisfy "no duplicated business logic" across TS and Python.

**D2 — Contracts are generated, not hand-written twice.** Pydantic models → OpenAPI → `openapi-typescript`
→ `@trustdesk/contracts`. CI fails if the generated file is out of date.

**D3 — Auth: argon2id + opaque server sessions owned by the AI service.** `POST /admin/auth/login` returns
a random 256-bit token; only its SHA-256 is stored (`sessions`). The admin app stores it in an `httpOnly;
Secure; SameSite=Lax` cookie on the admin domain and forwards it as `Authorization: Bearer` server-side.
Admin and AI service are on different domains (Vercel vs Railway/Fly), so no cross-site cookies are needed.
Next.js middleware only redirects for UX; every permission check runs in FastAPI (`require_role(...)`).
No paid auth provider is introduced.

**D4 — Tenant isolation is enforced twice.** (a) Every repository query filters by `tenant_id`; (b)
Postgres RLS on every tenant table (all objects in a private `trustdesk` schema), the runtime role
`trustdesk_app` is not the table owner and has `NOBYPASSRLS`, and each transaction runs
`SELECT set_config('app.tenant_id', :id, true)`. If the setting is missing the policy evaluates to NULL and
returns **no rows** (fail closed). Transaction-local settings work with Supabase's transaction pooler. The few
cross-tenant lookups (tenant by publishable key, session lookup, job claiming) go through narrow
`SECURITY DEFINER` functions. Details: `docs/database.md`.

**D5 — Embeddings: one column, partial HNSW indexes per dimension.** `chunk_embeddings.embedding` is an
untyped `vector`; each supported dimension (384/768/1024/1536) gets a partial HNSW index on
`(embedding::vector(N))` `WHERE dimension = N`, and queries always use the same cast + predicate — so
dimensions are never mixed in one index. Each `embedding_indexes` row records provider/model/dimension.
Changing model = build a new index in the background; the old one serves traffic until the new one is
complete, then it is swapped atomically. **Default dimension 1024**: BGE-M3 (local), Cohere
embed-multilingual-v3 and OpenAI text-embedding-3 (`dimensions=1024`) can all produce it.

**D6 — Streaming *verified* text, not raw model output.** Spec requires both token streaming and
verification before the visitor sees claims. The model streams; the service buffers to sentence boundaries,
verifies each sentence's citations against the retrieval set, and emits `token` events only for verified
sentences. Unsupported sentences are dropped and counted; if what remains is insufficient the workflow
switches to handoff. Nothing is emitted that has not been checked; no synthetic "typing" is generated.

**D7 — The model never chooses citation IDs.** Evidence is presented as `[E1]…[E5]`, mapped server-side to
chunk IDs from this request's retrieval set. Unknown markers are rejected. Numbers, prices, percentages and
dates in a sentence must appear in the cited evidence verbatim (normalized), otherwise the sentence is
removed. Confidence, language and `handoff_required` in the final structured output are computed by our
code, never taken from the model.

**D8 — Answerability is deterministic and runs before generation.** Signals: top rerank score, score
margin, number of chunks above threshold, query-term coverage, source freshness, metadata/tag compatibility,
and (P2) conflict detection. Policy and thresholds live in `rag/answerability.py` + tenant settings, are
independent of the LLM provider, and are stricter when the reranker is `none`. Confidence (HIGH/MEDIUM/LOW)
is derived from the same signals plus verification results.

**D9 — Provider adapters live in Python only.** The spec asks for TS and Python interfaces. Only the
Python service calls providers, so TS implementations would be dead code. TS gets the provider *types*
(names, config shapes) through `@trustdesk/contracts` / `@trustdesk/config`. Adding a provider = one Python
file + one registry line (`docs/providers.md`).

**D10 — Safe crawling.** Every fetch goes through `security/ssrf.py`: scheme allowlist (http/https),
domain allowlist, DNS resolution with every resolved address checked against private/loopback/link-local/
CGNAT/metadata (169.254.169.254, fd00:ec2::254) ranges, connection pinned to the validated IP, redirects
followed manually and re-validated, size and time limits. Crawl4AI is used for HTML cleaning/markdown on
HTML **we fetched safely**; its built-in browser fetching (JS rendering) is off by default because a
headless browser cannot be reliably pinned against DNS rebinding — see risk R2.

**D11 — Background jobs use Postgres, not a new service.** `indexing_jobs` and `webhook_deliveries`
are claimed with `FOR UPDATE SKIP LOCKED` by a worker process (same image, different command). No Redis/queue
is required; Redis remains an optional rate-limit store.

**D12 — Version activation is atomic.** A new `document_version` is built in the background (chunks +
embeddings) and `documents.active_version_id` is switched in one transaction only after success. A failed
re-index leaves the previous version serving. Unchanged content (same SHA-256 of normalized text) is
skipped; chunk-level embeddings are reused when a chunk's content hash matches.

**D13 — Default provider profile is `local`.** Ollama (generation, embeddings via `bge-m3`) and a local
cross-encoder (`bge-reranker-v2-m3`) via sentence-transformers. The project runs with zero paid APIs.
Cloud adapters (OpenAI, Anthropic, Cohere, Resend, Turnstile, Langfuse) activate only when configured;
their keys are required only if selected. No paid service is substituted silently.

## 5. Request flow (Phase 1)

```
widget ──POST /v1/chat/stream (publishable key + Origin)──▶ FastAPI
  ├─ resolve tenant by key, check Origin ∈ tenant.allowed_origins, rate limit, budget
  ├─ SSE: conversation_started
  └─ LangGraph:
     rewrite → hybrid_retrieve (40 vec + 40 FTS → RRF → dedupe → active/enabled filters)   [SSE: searching]
             → rerank (top 5)                                                               [SSE: reranking]
             → answerability_gate ──insufficient──▶ handoff → END                           [SSE: handoff]
             → generate (streamed) → verify (per sentence)                                  [SSE: token, citation]
             → verified ok ──▶ END   | too little survives ──▶ handoff → END
  └─ SSE: confidence, completed   (errors: sanitized `error` event with correlation ID)
```

## 6. Phase compatibility check

| Future feature | Extension point already in Phase 1 |
|---|---|
| Proof Peek (P2) | `citations.evidence_snapshot` + `supporting_span` persisted now |
| Proof Cards, Ask the Founder (P2) | `documents.tags` + metadata filter in retrieval |
| Page-aware greetings (P2) | `conversations.page_url`/`page_title` columns; never used as evidence |
| Knowledge Gap Report (P2) | `messages.answer_status` + `retrieval_trace` record refusals/low confidence |
| Language packs (P2) | `language` on chunks/messages; per-language `tsv_config`; widget i18n via JSON string tables |
| Verified Answers (P2) | retrieval source abstraction allows an extra top-priority source; new table only |
| Trust Receipt (P2) | messages + citations + document_version timestamps already stored |
| Source conflict detection (P2) | answerability signal slot `contradiction` (no-op in P1) |
| Public API /v1 + secret keys (P2) | all public routes already under `/v1`; `api_keys` table added in P2 |
| Evals / Ragas / golden set (P3) | `eval_runs` table; `trustdesk eval` command reserved |
| Redaction, retention, deletion (P3) | conversations cascade-delete; `retention_days` in settings |
| Billing, spend alerts (P3) | `usage_records` with `estimated_cost_usd` |

## 7. Technical risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **No Docker/Postgres on this machine** — migrations, RLS, pgvector and integration tests can't be verified | Install Docker Desktop, or provide an external Postgres 16 + pgvector URL. Until then only unit tests can run, and the report will say so |
| R2 | Crawl4AI's headless browser can bypass SSRF checks (DNS rebinding, subresource requests) | Safe-fetch HTML ourselves; JS rendering opt-in only, documented as requiring an egress proxy. Verify in a spike that Crawl4AI's cleaning works on supplied HTML without launching a browser |
| R3 | Sentence-level verification by lexical/embedding similarity is a weak proxy for entailment | Strict numeric/price check, conservative thresholds, handoff on doubt; optional LLM/NLI judge adapter later. Documented as a limitation, not a guarantee |
| R4 | Local models on CPU are slow and heavy (BGE-M3 + reranker ≈ 2×570M params, torch ≈ 2 GB image) | `[local]` extra and separate image tag; Ollama for embeddings; `none` reranker fallback with stricter gate |
| R5 | Publishable key + Origin is not authentication; non-browser clients can spoof Origin and burn budget | Per-tenant rate limits (Postgres store), monthly hard budget, captcha on lead submission |
| R6 | Turnstile/hCaptcha inside Shadow DOM — iframe rendering may not work in a shadow root | Spike early; fallback: render the captcha container in a light-DOM slot owned by the widget |
| R7 | Urdu has no Postgres stemmer; FTS weak for Urdu/Roman Urdu | `simple` config for non-English + vector retrieval carries multilingual recall; noted for P2 language packs |
| R8 | Forgotten `set_config` in a code path → empty results (fail closed) rather than leaks | Single session factory that always sets it; integration test asserts cross-tenant reads return zero rows as the app role |
| R9 | Scope: Phase 1 as specified (core RAG + widget + admin + wizard + 7 adapter families + 6 handoff channels + webhooks + CLI + CI + OSS docs) is several weeks of work | Build in vertical slices in the §20 order; each slice ends with tests run and docs updated; report states exactly what is done |

## 8. Execution order

Follows spec §20. Each step ends with its tests executed and this document's status updated.

1. Workspace scaffolding (pnpm/turbo, Python project, lint/type configs) and Docker Compose
2. Schema + migrations + RLS + seed (Acme Studio, marked DEMO)
3. Auth, sessions, RBAC, tenant scoping
4. Ingestion: safe fetch, sitemap, HTML/PDF/DOCX parsing, chunking, hashing, versioning, worker
5. Embedding adapters + hybrid retrieval + RRF
6. Rerank adapters + answerability + confidence
7. LangGraph generate/verify/handoff + prompts
8. SSE streaming endpoint
9. Widget
10. Admin dashboard + Setup Wizard + Playground
11. Handoff channels, leads, signed webhooks
12. CLI (`create-trustdesk`, `trustdesk doctor/ingest/migrate/export/import`)
13. Security tests, CI, OSS docs, final report
