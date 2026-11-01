# Ingestion

## Flow

```
Sources page ─► indexing_jobs (pending) ─► worker claims (FOR UPDATE SKIP LOCKED)
  website/sitemap: robots.txt Sitemap: → /sitemap.xml → (no sitemap) breadth-first link crawl
  upload:          stored file → PDF/DOCX parser
  each document:   parse → blocks → hash → unchanged? skip : new version (building)
                   → chunk → embed (reusing identical chunks' vectors) → activate atomically
```

Run the worker with `trustdesk worker` (started automatically by `trustdesk up`).

## Fetching (SSRF-safe)

All HTTP goes through `security/ssrf.py` — see [security.md](security.md). Only the organization's allowed
domains (and subdomains) are fetched; ports 80/443; max 5 redirects, each re-validated; 5 MB per page,
20 MB per sitemap; 0.2 s politeness delay between pages. JavaScript is **not** executed (risk R2 in
architecture.md); sites that render content only with JavaScript need a sitemap of server-rendered pages or
document uploads.

## Parsing

| Input | Parser | Structure kept |
|---|---|---|
| HTML | BeautifulSoup + lxml | `<main>`/`<article>` preferred; nav/footer/header/aside/forms/scripts/cookie banners removed; h1–h6, paragraphs, lists, tables (→ Markdown), code; title, `lang`, canonical URL |
| PDF | pypdf | text per page with page numbers; encrypted or image-only PDFs are rejected with a clear message (no OCR) |
| DOCX | python-docx | Heading styles, list styles, tables, document title |

Crawl4AI is listed in the original spec; it is an optional extra (`[crawl]`) and **not used** by the default
pipeline, because its browser fetching cannot be pinned against DNS rebinding.

## Chunking (`ingestion/chunker.py`)

- Target 500 tokens, max 600 (cl100k token counts), ~15% sentence-aligned overlap within a section.
- Never crosses a heading; each chunk stores `heading_path`, `section`, `parent_section_id`, page number,
  source URL, page title, language and document version.
- Tables, lists and code are atomic; an oversized table is split by rows with the header repeated.
- Configurable via `ChunkConfig(target_tokens, max_tokens, overlap_ratio)`.

## Versioning and states

Document status: `pending → crawling → parsing → chunking → embedding → indexed | failed | stale`.
A new version is built in state `building` inside one transaction; only when every chunk is embedded is
`documents.active_version_id` switched and the old version marked `superseded` (its chunks are deleted;
past citations keep their evidence snapshot). If anything fails, the transaction rolls back, the previous
version keeps serving and the error is shown on the document in the dashboard.

Unchanged content (same SHA-256 of normalized text) creates no version and costs no embeddings.

## Embedding index

Each organization has one active index recording provider, model and dimension (384/768/1024/1536, each
with its own partial HNSW index). If the configured model differs, indexing stops with a clear message.
`trustdesk reembed` builds a new index for every organization whose active index differs from the configured
model, then switches atomically and deletes the retired vectors; answers keep using the old index until the
switch. (*Planned:* trigger it from the dashboard.)
