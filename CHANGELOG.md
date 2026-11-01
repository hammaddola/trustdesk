# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning: [SemVer](https://semver.org/).

## [Unreleased] — 0.1.0 (Phase 1, in progress)

### Added
- AI service: ingestion (SSRF-safe crawl, sitemaps, PDF/DOCX), heading-aware chunking, versioning,
  hybrid retrieval (pgvector + full-text + RRF + rerank), answerability gate, LangGraph workflow,
  sentence-level citation verification, confidence levels, SSE streaming, handoff leads, usage budgets,
  audit log, rate limiting, provider adapters (Ollama, OpenAI, Anthropic, OpenAI-compatible, Cohere, local).
- PostgreSQL schema with Row-Level Security; embedded local Postgres for development (`trustdesk db-start`).
- Admin dashboard (Next.js): sign-in, first-run setup, Overview, Sources, Conversations, Leads (CSV),
  Insights, Playground, Settings.
- Embeddable widget in Shadow DOM (single ~82 KB gzip script) with citations, confidence meter and handoff.
- `trustdesk up`: whole project on one port.
