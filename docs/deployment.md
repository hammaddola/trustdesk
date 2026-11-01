# Deployment

**Verified so far: local single-machine run (`trustdesk up`) on Windows 11.** Nothing below has been
deployment-tested yet; treat it as the intended setup, not a guarantee.

## Option 1 — one server (simplest)

Run `trustdesk up --port 3100` behind a TLS reverse proxy (Caddy/nginx) on a VM. One public port serves the
dashboard, `/trustdesk.js`, `/demo` and `/v1/*`; the AI service listens on `127.0.0.1:8000` only. Use a real
PostgreSQL 15+ with pgvector (managed or self-hosted) instead of the embedded one:

1. `DIRECT_DATABASE_URL` = owner role (migrations); `DATABASE_URL` = `trustdesk_app` role.
2. `trustdesk db-bootstrap` (creates the role, runs migrations, applies grants).
3. `TRUSTDESK_ENV=production`, set `TRUSTDESK_ENCRYPTION_KEY`, `TRUSTDESK_SETUP_TOKEN`, real providers,
   `EMAIL_PROVIDER=smtp|resend`, captcha keys.
4. Configure uvicorn `FORWARDED_ALLOW_IPS` for your proxy so rate limits see real client IPs.
5. `trustdesk doctor` must be all OK.

## Option 2 — split hosting (original spec)

| Part | Host | Notes |
|---|---|---|
| Dashboard + widget script | Vercel (or any Node host) | `apps/admin` with `AI_SERVICE_URL` (server-only) pointing at the API; the widget is served from `public/trustdesk.js` |
| AI service + worker | Railway / Fly.io | two processes from one image: `trustdesk serve` and `trustdesk worker` |
| Database | Supabase Postgres (pgvector enabled) | use the **direct** connection for migrations; tables live in schema `trustdesk`, not exposed via PostgREST |

Widget origins are configured per organization in Settings; the dashboard never needs CORS because it calls
the API server-to-server.

## Docker

*Planned:* Dockerfiles and `docker-compose.yml` (Postgres + pgvector, API, worker, web, optional Ollama).
They are not in the repository yet because they could not be verified on the development machine (no Docker).

## Migrations

`trustdesk migrate` (or `db-bootstrap`, which also creates the runtime role and grants). Migrations are
forward-only in production; take a database backup first.
