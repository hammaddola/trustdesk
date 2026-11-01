# Security

Status reflects the code as of 2026-11-01. "Tested" means an automated test exercises it.

## Threat model in one paragraph

Visitors are anonymous and untrusted. Website content and uploaded documents are untrusted *data* (they
may contain prompt-injection text). Admins are authenticated per organization. The AI service holds all
secrets and all business logic; browsers never receive secret keys. In platform mode, organizations must
never see each other's data.

## Controls

| Area | Control | Where | Tested |
|---|---|---|---|
| Tenant isolation | Every query filters `tenant_id`; Postgres RLS on every tenant table; runtime role `trustdesk_app` is not owner, no `BYPASSRLS`; missing tenant context returns zero rows | `db/session.py`, migration 0001 | yes — `tests/integration` (cross-tenant read/update/insert) |
| Cross-tenant entry points | Narrow `SECURITY DEFINER` functions with fixed `search_path` (key lookup, memberships, job claim, tenant creation) | migration 0001 | yes (indirectly) |
| Supabase/PostgREST exposure | All tables in the `trustdesk` schema, not `public`; `REVOKE ALL … FROM PUBLIC` | migration, `cli/db.py` | doctor check |
| Admin auth | argon2id passwords; random 256-bit opaque sessions, only SHA-256 stored; 12 h TTL; each attempt atomically reserves a slot (refunded on success) keyed on (email, client network) and client network (IPv6 grouped by /64); per account, repeated failures from anywhere add progressive delays instead of a hard lockout, so others cannot lock an owner out; constant-time dummy hash for unknown emails | `auth/` | yes (API tests) |
| Authorization | Every admin endpoint requires a valid session server-side; owner-only settings; Next.js middleware is UX only | `api/deps.py` | yes |
| Admin cookie | `httpOnly`, `SameSite=Lax`, `Secure` in production; token never exposed to browser JS; CSV export proxied server-side | `apps/admin` | manual |
| CSRF | Next.js server actions enforce same-origin; API uses bearer tokens (no ambient credentials) | — | — |
| First-run setup | Requires `TRUSTDESK_SETUP_TOKEN`, only while zero users exist, serialized with an advisory lock | `api/admin_auth.py` | no |
| Widget CORS | Per-organization exact-origin allowlist (normalized); `*` rejected in DB CHECK, API validation and settings | middleware, settings | yes (allowed, lookalike, scheme, port, null) |
| SSRF | http/https only, ports 80/443, no credentials/IP literals/local names; DNS resolved **at connect time** and every address must be public (blocks loopback, private, link-local, CGNAT, metadata incl. IPv6 IMDS, IPv4-mapped); redirects re-validated; size/time limits; env proxies ignored | `security/ssrf.py` | yes (incl. DNS-rebinding simulation) |
| Crawl scope | Organization's allowed domains only; canonical links outside the allowlist ignored | `ingestion/worker.py` | partly |
| Uploads | Size limit before parsing; content sniffing (magic bytes), not filename/MIME; server-generated storage keys; path traversal blocked; encrypted PDFs rejected; DOCX zip-bomb check (uncompressed size and ratio) before parsing; PDF page and extracted-text caps | `api/admin_sources.py`, `storage/local.py` | yes (sniffing) |
| XML | Sitemaps parsed without entity resolution, DTDs or network; gzip bounded (bomb guard) | `ingestion/sitemap.py` | yes (XXE) |
| Prompt injection | Evidence HTML-escaped inside `<evidence>` tags; system prompt treats it as untrusted; **independent verification removes unsupported claims regardless of what the model does** | `rag/prompts`, `rag/verification.py` | yes |
| Citations | Model sees only `[E1..E5]`; markers mapped server-side to this request's evidence for this tenant on active versions; numbers must appear in cited evidence | `rag/verification.py` | yes |
| Output | Widget renders text (no HTML injection); only http(s) links; `rel=noopener noreferrer` | widget | yes |
| CSV export | Formula-injection neutralized | `api/admin_data.py` | no |
| Errors | Sanitized responses with request ID; validation errors never echo input | `main.py` | yes |
| Headers | nosniff, frame-deny (dashboard), CSP on API, referrer policy | middleware, next.config | yes (API) |
| Limits | Request body 64 KB (upload 20 MB), enforced on bytes actually received (chunked bodies included); chat 20/min/IP/org; leads 5/10 min; monthly budget hard stop | middleware, `api/public.py` | partly |
| Logging | JSON logs with request IDs; no credentials, message bodies or raw IPs (hashed) in logs/audit | `main.py`, `audit.py` | — |
| Secrets | Server-only env vars; only required for selected providers; mock providers refused in production | `config/settings.py` | — |

## Known gaps (not yet resolved)

- Document parsing runs in-process; a subprocess with CPU/memory limits and a timeout would add isolation.

- Rate limits key on client IP; behind a proxy set uvicorn `FORWARDED_ALLOW_IPS` correctly or they collapse.
- The publishable key + Origin is not authentication: non-browser clients can spoof Origin. Budgets and rate
  limits bound the damage.
- Lexical/numeric verification is a conservative proxy for entailment, not proof (architecture risk R3).
- JS-rendered crawling (headless browser) is intentionally not enabled (risk R2).
- No external penetration test has been performed. **Do not treat this as production-ready.**

## Reporting

See [SECURITY.md](../SECURITY.md).
