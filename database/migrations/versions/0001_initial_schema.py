"""Initial schema: tenancy, knowledge, conversations, integrations, usage, audit + RLS.

Revision ID: 0001
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# Every tenant-owned table gets RLS with this policy (see docs/database.md).
TENANT_TABLES = [
    "tenants",  # policy uses id instead of tenant_id
    "tenant_memberships",
    "tenant_settings",
    "embedding_indexes",
    "sources",
    "documents",
    "document_versions",
    "chunks",
    "chunk_embeddings",
    "indexing_jobs",
    "conversations",
    "messages",
    "citations",
    "feedback",
    "leads",
    "webhook_endpoints",
    "webhook_deliveries",
    "usage_records",
    "eval_runs",
    "audit_logs",
]

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS trustdesk;
SET search_path = trustdesk, public, extensions;

-- ---------- identity & tenancy ----------
CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  public_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  is_demo boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE CHECK (length(email) <= 320 AND email = lower(email)),
  password_hash text NOT NULL,
  display_name text,
  is_active boolean NOT NULL DEFAULT true,
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenant_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner','admin')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, user_id)
);
CREATE INDEX ON tenant_memberships (user_id);

CREATE TABLE sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  token_hash bytea NOT NULL UNIQUE,
  active_tenant_id uuid REFERENCES tenants ON DELETE SET NULL,
  expires_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  ip_hash bytea,
  user_agent text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON sessions (expires_at);
CREATE INDEX ON sessions (user_id);

CREATE TABLE embedding_indexes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  provider text NOT NULL,
  model text NOT NULL,
  dimension smallint NOT NULL CHECK (dimension IN (384,768,1024,1536)),
  status text NOT NULL DEFAULT 'building' CHECK (status IN ('building','active','retired')),
  created_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz
);
CREATE UNIQUE INDEX embedding_indexes_one_active ON embedding_indexes (tenant_id) WHERE status = 'active';

CREATE TABLE tenant_settings (
  tenant_id uuid PRIMARY KEY REFERENCES tenants ON DELETE CASCADE,
  schema_version int NOT NULL DEFAULT 1,
  organization_name text NOT NULL,
  description text,
  industry text,
  audience text,
  website_urls text[] NOT NULL DEFAULT '{}',
  allowed_domains text[] NOT NULL DEFAULT '{}',
  allowed_origins text[] NOT NULL DEFAULT '{}' CHECK (NOT ('*' = ANY (allowed_origins))),
  founder_name text,
  founder_role text,
  default_language text NOT NULL DEFAULT 'en',
  enabled_languages text[] NOT NULL DEFAULT '{en}',
  timezone text NOT NULL DEFAULT 'UTC',
  llm_provider text,
  llm_model text,
  reranker_provider text,
  confidence_threshold numeric(4,3) NOT NULL DEFAULT 0.35 CHECK (confidence_threshold BETWEEN 0 AND 1),
  max_answer_tokens int NOT NULL DEFAULT 600 CHECK (max_answer_tokens BETWEEN 50 AND 4000),
  monthly_budget_usd numeric(12,2) CHECK (monthly_budget_usd >= 0),
  budget_warning_pct smallint NOT NULL DEFAULT 80 CHECK (budget_warning_pct BETWEEN 1 AND 100),
  budget_hard_limit boolean NOT NULL DEFAULT true,
  retention_days int CHECK (retention_days > 0),
  greeting text,
  widget_theme jsonb NOT NULL DEFAULT '{}',
  handoff_channels jsonb NOT NULL DEFAULT '{}',
  setup_completed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- knowledge ----------
CREATE TABLE sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('website','sitemap','upload')),
  root_url text,
  include_patterns text[] NOT NULL DEFAULT '{}',
  exclude_patterns text[] NOT NULL DEFAULT '{}',
  max_pages int NOT NULL DEFAULT 200 CHECK (max_pages BETWEEN 1 AND 10000),
  enabled boolean NOT NULL DEFAULT true,
  tags text[] NOT NULL DEFAULT '{}',
  created_by uuid REFERENCES users ON DELETE SET NULL,
  last_crawled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'upload') = (root_url IS NULL))
);
CREATE INDEX ON sources (tenant_id, created_at DESC);

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES sources ON DELETE CASCADE,
  source_type text NOT NULL CHECK (source_type IN ('web_page','pdf','docx')),
  canonical_url text,
  storage_key text,
  title text,
  language text,
  tags text[] NOT NULL DEFAULT '{}',
  enabled boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','crawling','parsing','chunking','embedding','indexed','failed','stale')),
  last_error text,
  active_version_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON documents (tenant_id, status);
CREATE INDEX ON documents (source_id);
CREATE INDEX ON documents USING gin (tags);
CREATE UNIQUE INDEX documents_tenant_url ON documents (tenant_id, canonical_url) WHERE canonical_url IS NOT NULL;

CREATE TABLE document_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  version_no int NOT NULL CHECK (version_no > 0),
  content_hash char(64) NOT NULL,
  state text NOT NULL DEFAULT 'building' CHECK (state IN ('building','active','superseded','failed')),
  title text,
  source_last_modified timestamptz,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  byte_size int,
  raw_storage_key text,
  metadata jsonb NOT NULL DEFAULT '{}',
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  UNIQUE (document_id, version_no)
);
CREATE INDEX ON document_versions (document_id, content_hash);
CREATE INDEX ON document_versions (tenant_id, state);

ALTER TABLE documents ADD CONSTRAINT documents_active_version_fk
  FOREIGN KEY (active_version_id) REFERENCES document_versions ON DELETE SET NULL
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  document_version_id uuid NOT NULL REFERENCES document_versions ON DELETE CASCADE,
  ordinal int NOT NULL,
  content text NOT NULL,
  token_count int NOT NULL,
  content_hash char(64) NOT NULL,
  source_url text,
  page_title text,
  section text,
  heading_path text[] NOT NULL DEFAULT '{}',
  parent_section_id text,
  page_number int,
  language text,
  tsv_config regconfig NOT NULL DEFAULT 'simple',
  tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector(tsv_config, coalesce(page_title,'') || ' ' || coalesce(section,'')), 'A') ||
    setweight(to_tsvector(tsv_config, content), 'B')
  ) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_version_id, ordinal)
);
CREATE INDEX ON chunks USING gin (tsv);
CREATE INDEX ON chunks (tenant_id, document_version_id);
CREATE INDEX ON chunks (tenant_id, content_hash);

CREATE TABLE chunk_embeddings (
  chunk_id uuid NOT NULL REFERENCES chunks ON DELETE CASCADE,
  embedding_index_id uuid NOT NULL REFERENCES embedding_indexes ON DELETE CASCADE,
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  dimension smallint NOT NULL CHECK (dimension IN (384,768,1024,1536)),
  embedding vector NOT NULL CHECK (vector_dims(embedding) = dimension),
  PRIMARY KEY (chunk_id, embedding_index_id)
);
CREATE INDEX ON chunk_embeddings (tenant_id, embedding_index_id);
-- One partial HNSW index per dimension; queries must use the same cast + predicate.
CREATE INDEX chunk_embeddings_hnsw_384 ON chunk_embeddings
  USING hnsw ((embedding::vector(384)) vector_cosine_ops) WHERE dimension = 384;
CREATE INDEX chunk_embeddings_hnsw_768 ON chunk_embeddings
  USING hnsw ((embedding::vector(768)) vector_cosine_ops) WHERE dimension = 768;
CREATE INDEX chunk_embeddings_hnsw_1024 ON chunk_embeddings
  USING hnsw ((embedding::vector(1024)) vector_cosine_ops) WHERE dimension = 1024;
CREATE INDEX chunk_embeddings_hnsw_1536 ON chunk_embeddings
  USING hnsw ((embedding::vector(1536)) vector_cosine_ops) WHERE dimension = 1536;

CREATE TABLE indexing_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES sources ON DELETE CASCADE,
  document_id uuid REFERENCES documents ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('crawl','ingest_file','reindex','reembed')),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','crawling','parsing','chunking','embedding','indexed','failed','stale')),
  progress jsonb NOT NULL DEFAULT '{}',
  error_code text,
  error_message text,
  attempts smallint NOT NULL DEFAULT 0,
  locked_by text,
  locked_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX indexing_jobs_pending ON indexing_jobs (created_at) WHERE status = 'pending';
CREATE INDEX ON indexing_jobs (tenant_id, created_at DESC);

-- ---------- conversations ----------
CREATE TABLE conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  visitor_id uuid NOT NULL,
  channel text NOT NULL CHECK (channel IN ('widget','playground')),
  language text,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','handed_off','closed')),
  page_url text,
  page_title text,
  message_count int NOT NULL DEFAULT 0,
  started_at timestamptz NOT NULL DEFAULT now(),
  last_message_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON conversations (tenant_id, last_message_at DESC);
CREATE INDEX ON conversations (tenant_id, status);

CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  conversation_id uuid NOT NULL REFERENCES conversations ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('user','assistant')),
  content text NOT NULL,
  rewritten_query text,
  language text,
  answer_status text CHECK (answer_status IN ('answered','partial','refused','handoff','error')),
  confidence text CHECK (confidence IN ('high','medium','low')),
  handoff_required boolean NOT NULL DEFAULT false,
  handoff_summary text,
  prompt_version text,
  llm_provider text,
  llm_model text,
  input_tokens int,
  output_tokens int,
  latency_ms int,
  request_id text,
  trace_id text,
  retrieval_trace jsonb,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (role = 'assistant' OR answer_status IS NULL)
);
CREATE INDEX ON messages (conversation_id, created_at);
CREATE INDEX ON messages (tenant_id, created_at DESC);
CREATE INDEX ON messages (tenant_id, confidence);
CREATE INDEX ON messages USING gin (tsv);

CREATE TABLE citations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  message_id uuid NOT NULL REFERENCES messages ON DELETE CASCADE,
  marker smallint NOT NULL CHECK (marker BETWEEN 1 AND 20),
  chunk_id uuid REFERENCES chunks ON DELETE SET NULL,
  document_version_id uuid REFERENCES document_versions ON DELETE SET NULL,
  source_url text,
  page_title text,
  section text,
  evidence_snapshot text NOT NULL,
  supporting_span text,
  support_score real,
  source_updated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (message_id, marker)
);
CREATE INDEX ON citations (tenant_id, chunk_id);

CREATE TABLE feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  message_id uuid NOT NULL UNIQUE REFERENCES messages ON DELETE CASCADE,
  rating text NOT NULL CHECK (rating IN ('helpful','not_helpful')),
  comment text CHECK (length(comment) <= 2000),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON feedback (tenant_id, created_at DESC);

CREATE TABLE leads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  conversation_id uuid REFERENCES conversations ON DELETE SET NULL,
  channel text NOT NULL CHECK (channel IN ('email','whatsapp','booking','slack','telegram','webhook')),
  name text CHECK (length(name) <= 200),
  email text CHECK (length(email) <= 320),
  phone text CHECK (length(phone) <= 40),
  message text CHECK (length(message) <= 5000),
  summary text,
  source text NOT NULL DEFAULT 'widget' CHECK (source IN ('widget','playground','api')),
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','contacted','qualified','closed','spam')),
  idempotency_key text NOT NULL,
  consented_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX ON leads (tenant_id, status, created_at DESC);

-- ---------- integrations, cost, audit ----------
CREATE TABLE webhook_endpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  url text NOT NULL,
  secret_encrypted bytea NOT NULL,
  events text[] NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON webhook_endpoints (tenant_id);

CREATE TABLE webhook_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  endpoint_id uuid NOT NULL REFERENCES webhook_endpoints ON DELETE CASCADE,
  event text NOT NULL,
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','delivered','failed','dead')),
  attempts smallint NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_status_code int,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX webhook_deliveries_due ON webhook_deliveries (next_attempt_at) WHERE status = 'pending';

CREATE TABLE usage_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('llm','embedding','rerank')),
  provider text NOT NULL,
  model text NOT NULL,
  input_tokens int NOT NULL DEFAULT 0,
  output_tokens int NOT NULL DEFAULT 0,
  units int NOT NULL DEFAULT 0,
  estimated_cost_usd numeric(12,6) NOT NULL DEFAULT 0,
  message_id uuid REFERENCES messages ON DELETE SET NULL,
  request_id text,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON usage_records (tenant_id, occurred_at);

CREATE UNLOGGED TABLE rate_limit_buckets (
  bucket_key text NOT NULL,
  window_start timestamptz NOT NULL,
  count int NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket_key, window_start)
);

CREATE TABLE eval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants ON DELETE CASCADE,
  dataset text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','completed','failed')),
  prompt_version text,
  config jsonb NOT NULL DEFAULT '{}',
  metrics jsonb NOT NULL DEFAULT '{}',
  faithfulness numeric(4,3),
  started_at timestamptz,
  finished_at timestamptz
);

CREATE TABLE audit_logs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id uuid REFERENCES tenants ON DELETE SET NULL,
  actor_user_id uuid REFERENCES users ON DELETE SET NULL,
  action text NOT NULL,
  target_type text,
  target_id text,
  request_id text,
  ip_hash bytea,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_logs (tenant_id, created_at DESC);

-- ---------- cross-tenant entry points (owner-privileged, narrow) ----------
CREATE FUNCTION resolve_public_key(p_key text)
RETURNS TABLE (tenant_id uuid, status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = trustdesk, pg_temp AS $$
  SELECT id, status FROM trustdesk.tenants WHERE public_key = p_key
$$;

CREATE FUNCTION user_memberships(p_user uuid)
RETURNS TABLE (tenant_id uuid, tenant_name text, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = trustdesk, pg_temp AS $$
  SELECT m.tenant_id, t.name, m.role
  FROM trustdesk.tenant_memberships m JOIN trustdesk.tenants t ON t.id = m.tenant_id
  WHERE m.user_id = p_user AND t.status = 'active'
  ORDER BY t.name
$$;

CREATE FUNCTION count_users() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = trustdesk, pg_temp AS $$
  SELECT count(*) FROM trustdesk.users
$$;

-- Distinct embedding configurations in use (no tenant data), for `trustdesk doctor`.
CREATE FUNCTION active_embedding_configs()
RETURNS TABLE (provider text, model text, dimension smallint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = trustdesk, pg_temp AS $$
  SELECT DISTINCT provider, model, dimension FROM trustdesk.embedding_indexes WHERE status = 'active'
$$;

-- Creates an organization. RLS forbids inserting a tenant row without that tenant's context.
CREATE FUNCTION create_tenant(p_slug text, p_name text, p_public_key text, p_is_demo boolean)
RETURNS uuid
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = trustdesk, pg_temp AS $$
  INSERT INTO trustdesk.tenants (slug, name, public_key, is_demo)
  VALUES (p_slug, p_name, p_public_key, p_is_demo) RETURNING id
$$;

-- Claims one pending job; worker must then set app.tenant_id to the returned tenant.
CREATE FUNCTION claim_indexing_job(p_worker text)
RETURNS TABLE (job_id uuid, tenant_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = trustdesk, pg_temp AS $$
  UPDATE trustdesk.indexing_jobs j
     SET status = 'crawling', locked_by = p_worker, locked_at = now(),
         started_at = coalesce(started_at, now()), attempts = attempts + 1
   WHERE j.id = (SELECT id FROM trustdesk.indexing_jobs
                  WHERE status = 'pending' ORDER BY created_at
                  FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING j.id, j.tenant_id
$$;

CREATE FUNCTION claim_webhook_delivery(p_worker text)
RETURNS TABLE (delivery_id uuid, tenant_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = trustdesk, pg_temp AS $$
  UPDATE trustdesk.webhook_deliveries d
     SET attempts = attempts + 1, next_attempt_at = now() + interval '5 minutes'
   WHERE d.id = (SELECT id FROM trustdesk.webhook_deliveries
                  WHERE status = 'pending' AND next_attempt_at <= now()
                  ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING d.id, d.tenant_id
$$;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TENANT_TABLES:
        col = "id" if table == "tenants" else "tenant_id"
        op.execute(f"ALTER TABLE trustdesk.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON trustdesk.{table} "
            f"USING ({col} = {TENANT_GUC}) WITH CHECK ({col} = {TENANT_GUC})"
        )
    # Grants to the runtime role are applied by `trustdesk db-bootstrap` (one place for privileges).
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA trustdesk FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP SCHEMA trustdesk CASCADE")
