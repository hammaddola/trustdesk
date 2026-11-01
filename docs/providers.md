# Providers

Every external service is an adapter behind a Python `Protocol` in
`services/ai/src/trustdesk_ai/providers/base.py`. Only keys for the **selected** providers are required.

| Kind | Implementations | Select with |
|---|---|---|
| LLM | `ollama`, `openai`, `anthropic`, `openai_compat` (Groq, Together, vLLM, LM Studio, Gemini OpenAI endpoint), `mock` (dev) | `LLM_PROVIDER`, `LLM_MODEL` (per-organization override in Settings) |
| Embeddings | `ollama`, `local` (sentence-transformers, `[local]` extra), `openai` (requests `EMBEDDING_DIMENSION`), `openai_compat` (e.g. Gemini), `cohere`, `mock` (dev) | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` |
| Reranker | `local` cross-encoder (`[local]`), `cohere`, `none` (RRF order + stricter gate), `mock` (dev) | `RERANKER_PROVIDER`, `RERANKER_MODEL` |
| Email | `console` (dev; disabled in production), `smtp`, `resend` | `EMAIL_PROVIDER` |
| Captcha | `none`, `turnstile`, `hcaptcha` (server-side token validation, fail closed) | `CAPTCHA_PROVIDER`, `*_SITE_KEY`, `*_SECRET_KEY` |
| File storage | `local` | `STORAGE_PROVIDER` — *S3 adapter planned* |
| Rate-limit store | `postgres` | `RATE_LIMIT_STORE` — *Redis adapter planned* |

Mock providers never invent content (the mock LLM quotes evidence verbatim) and are refused when
`TRUSTDESK_ENV=production`.

## Google Gemini (tested 2026-11-01)

Via Gemini's OpenAI-compatible endpoint:

```
LLM_PROVIDER=openai_compat
LLM_MODEL=gemini-3.1-flash-lite
LLM_REASONING_EFFORT=none        # thinking tokens otherwise eat MAX_ANSWER_TOKENS and truncate answers
EMBEDDING_PROVIDER=openai_compat
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMENSION=1024
RERANKER_PROVIDER=none           # Gemini has no reranker; the gate is stricter without one
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_API_KEY=<your Gemini API key>
```

Free-tier quotas are small and per model (e.g. 20 requests/day for `gemini-3.5-flash` at the time of
testing). When exceeded, visitors get a clean "can't answer right now" error — never an invented answer.
After changing embedding settings run `trustdesk reembed` (the old index serves until the new one is ready).

## Adding a provider

1. Create one file, e.g. `providers/llm/mistral.py`, with a class implementing the protocol (`name`, `model`,
   `complete`, `stream`). Raise `ProviderError` with a sanitized message on failures — never include keys or
   prompt text.
2. Add one branch in `providers/registry.py` (`build_llm` / `build_embeddings` / `build_reranker`).
3. Add any key to `config/settings.py` and to the "required when selected" check, and to `.env.example`.
4. Add a unit test with a mocked HTTP transport.

## Costs

Local providers cost $0. Cloud prices change, so none are hard-coded: set `MODEL_PRICES_JSON`, e.g.
`{"openai/gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.6}}`. Without a price, usage is recorded
with cost 0 and budgets cannot protect against that model (the service logs a warning once).
