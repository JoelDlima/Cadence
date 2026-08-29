-- PHASE 9: Audit DLQ + journey_summaries tables for the Supabase Edge
-- Functions. The DLQ captures failed sync batches (when the engine is
-- unreachable) and the journey_summaries table stores the LLM-generated
-- merchant-facing summary from the cadence-llm-summary Edge Function.

CREATE TABLE IF NOT EXISTS audit_dlq (
    id            BIGSERIAL PRIMARY KEY,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source       TEXT NOT NULL,                 -- "engine_sync", "test_inject", "llm_summary", etc.
    batch_id     TEXT,
    payload      JSONB NOT NULL,
    error        TEXT,
    retried_at   TIMESTAMPTZ,
    retry_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_audit_dlq_captured ON audit_dlq (captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_dlq_source ON audit_dlq (source);
ALTER TABLE audit_dlq ENABLE ROW LEVEL SECURITY;
-- Only service_role bypasses; anon and authenticated get nothing.

CREATE TABLE IF NOT EXISTS journey_summaries (
    journey_id   TEXT PRIMARY KEY,
    summary      TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model        TEXT
);
ALTER TABLE journey_summaries ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS cadence_edge_log (
    id          BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_id    TEXT,
    event_name  TEXT,
    payload     JSONB
);
CREATE INDEX IF NOT EXISTS idx_cadence_edge_log_received
    ON cadence_edge_log (received_at DESC);
ALTER TABLE cadence_edge_log ENABLE ROW LEVEL SECURITY;
