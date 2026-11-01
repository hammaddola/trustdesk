# API

The full, always-current schema is the OpenAPI document generated from the FastAPI models:
`http://localhost:3100/v1/…` (proxied) — interactive docs at `http://127.0.0.1:8000/docs` in development
(disabled in production). A copy is committed at `packages/contracts/openapi.json` and TypeScript types are
generated from it (`pnpm --filter @trustdesk/contracts generate`).

## Public (widget) API — `/v1/public/{publishable_key}/…`

Authenticated by the publishable key in the path **and** the browser `Origin`, which must exactly match the
organization's allowed origins (preflight included).

| Method | Path | Purpose |
|---|---|---|
| GET | `/config` | Widget configuration (name, greeting, theme, enabled handoff channels, captcha site key). Never includes team email addresses or secrets. |
| POST | `/chat/stream` | Ask a question; **Server-Sent Events** response. Body: `{message, visitor_id, conversation_id?, page_url?, page_title?}` |
| POST | `/feedback` | `{message_id, visitor_id, rating: helpful|not_helpful, comment?}` — only for the visitor's own conversation |
| POST | `/leads` | Handoff: `{channel: email|whatsapp|booking, visitor_id, idempotency_key, …}`. Email requires `email`, `consent=true`, and a captcha token when configured. Saved before `201` is returned; repeated keys return the same lead. |

### SSE events (`text/event-stream`)

Each event has an `id`, a name and JSON `data`. Heartbeats are `: ping` comments every 15 s. Events are only
emitted for work that actually happens (e.g. no `reranking` without a reranker).

| Event | Data |
|---|---|
| `conversation_started` | `{conversation_id}` |
| `searching` | `{}` — retrieval started |
| `reranking` | `{}` — reranker running |
| `citation` | `{marker, title, url, section, snippet, updated_at}` — emitted before the sentence that first uses it |
| `token` | `{text}` — one **verified** sentence (with renumbered `[n]` markers) |
| `handoff` | `{message, summary}` — evidence insufficient; offer a human |
| `confidence` | `{level: high|medium|low}` |
| `completed` | `{message_id, conversation_id, status, handoff_required, language}` |
| `error` | `{message, request_id}` — sanitized |

Closing the connection cancels generation server-side.

## Admin API — `/v1/admin/…`

`Authorization: Bearer <session token>` (obtained from `POST /v1/admin/auth/login`). The dashboard keeps the
token in an httpOnly cookie and calls the API server-side. Owner-only: `PATCH /settings`.

| Area | Endpoints |
|---|---|
| Auth | `POST auth/login`, `POST auth/logout`, `GET auth/session`, `POST auth/switch-tenant`, `GET setup/status`, `POST setup` |
| Sources | `GET/POST sources`, `POST sources/upload` (multipart), `GET/PATCH/DELETE sources/{id}`, `POST sources/{id}/reindex`, `PATCH documents/{id}` |
| Data | `GET overview?days=`, `GET conversations?q&since&until&confidence&handoff&channel`, `GET conversations/{id}`, `GET leads?q&status`, `PATCH leads/{id}`, `GET leads.csv` |
| Settings | `GET/PATCH settings` |
| Playground | `POST playground` — runs the real pipeline (channel `playground`) and returns answer, events, citations and the full retrieval trace |

Errors: `{"error": "...", "request_id": "..."}`; validation errors add `fields: [{field, message}]` and never
echo submitted values.
