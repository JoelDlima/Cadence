-- Cadence Supabase schema (Phase 4).
-- Run ONCE in Supabase Studio -> SQL Editor.
--
-- This file is the source of truth for the cloud-mirror tables. After running
-- it the first time, Supabase's PostgREST auto-discovers the three tables
-- and the service_role key (in `Cadence/.env` as SUPABASE_SERVICE_KEY) can
-- POST to them with the `Prefer: resolution=merge-duplicates` header for
-- upsert behavior.
--
-- SECURITY: this schema enables RLS on every table with NO policies. That
-- means the anon and authenticated roles get DENIED by default. Only the
-- service_role (which bypasses RLS) can read or write. This is the right
-- posture for a backend mirror: external readers do not exist.

-- ---------------------------------------------------------------------------
-- 1. webhook_inbox
--
-- Razorpay webhooks land here first (via the Supabase Edge Function) so the
-- laptop-behind-NAT can poll them down through the same gateway the FastAPI
-- app exposes directly. The local engine processes each row exactly once.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS webhook_inbox (
    id            BIGSERIAL PRIMARY KEY,
    event_id      TEXT NOT NULL UNIQUE,             -- Razorpay X-Razorpay-Event-Id (idempotency key)
    payload       JSONB NOT NULL,                   -- raw Razorpay event body
    signature    TEXT,                              -- X-Razorpay-Signature from header
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,                      -- NULL = unprocessed
    processed    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_webhook_inbox_unprocessed
    ON webhook_inbox (received_at)
 WHERE processed = FALSE;

-- ---------------------------------------------------------------------------
-- 2. journeys_mirror
--
-- One row per recovery journey, mirrored one-way from the local SQLite
-- `journeys` table. Read by anyone with the service_role key (i.e. the
-- FastAPI app's /api/cloud/status endpoint and any future dashboard).
-- Mirror of the local DB; the local DB remains the source of truth.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journeys_mirror (
    journey_id      TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    state           TEXT NOT NULL,
    root_cause      TEXT,
    classify_source TEXT,
    amount_minor    BIGINT,
    attempts_used   INTEGER NOT NULL DEFAULT 0,
    touches_used    INTEGER NOT NULL DEFAULT 0,
    opened_at       TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    mirrored_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_journeys_mirror_state
    ON journeys_mirror (state);
CREATE INDEX IF NOT EXISTS idx_journeys_mirror_updated
    ON journeys_mirror (updated_at DESC);

-- ---------------------------------------------------------------------------
-- 3. metrics_daily
--
-- One row per day with the headline KPIs. Upserted by the local worker
-- every 30 seconds (configurable via _MIRROR_INTERVAL_SECONDS in app.py).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metrics_daily (
    day                  DATE PRIMARY KEY,
    journeys_opened      INTEGER NOT NULL DEFAULT 0,
    recovered_count      INTEGER NOT NULL DEFAULT 0,
    recovered_inr_major  NUMERIC(14, 2) NOT NULL DEFAULT 0,
    violations           INTEGER NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 4. chaos_drill_runs (optional, useful for the pitch demo)
--
-- If you want a leaderboard of chaos-drill runs in the cloud mirror, this
-- table records the outcome of each drill. Cadence does NOT write to this
-- table by default; it is here for judges / future dashboards.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chaos_drill_runs (
    id           BIGSERIAL PRIMARY KEY,
    drill        TEXT NOT NULL,
    passed       BOOLEAN NOT NULL,
    detail       TEXT NOT NULL,
    duration_ms  INTEGER NOT NULL,
    run_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chaos_drill_runs_drill
    ON chaos_drill_runs (drill, run_at DESC);

-- ---------------------------------------------------------------------------
-- Row-Level Security: deny all to anon and authenticated; service_role bypasses.
-- ---------------------------------------------------------------------------
ALTER TABLE webhook_inbox       ENABLE ROW LEVEL SECURITY;
ALTER TABLE journeys_mirror     ENABLE ROW LEVEL SECURITY;
ALTER TABLE metrics_daily        ENABLE ROW LEVEL SECURITY;
ALTER TABLE chaos_drill_runs    ENABLE ROW LEVEL SECURITY;

-- No policies => only service_role bypasses RLS and can read/write.
-- This is the right posture for a backend mirror; external readers do not exist.

-- ---------------------------------------------------------------------------
-- Helper view: the "yesterday vs today" comparison a judge will click first.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW daily_metrics_with_delta AS
SELECT
    day,
    journeys_opened,
    recovered_count,
    recovered_inr_major,
    violations,
    LAG(recovered_count)        OVER (ORDER BY day) AS recovered_count_yesterday,
    LAG(recovered_inr_major)    OVER (ORDER BY day) AS recovered_inr_major_yesterday,
    recovered_count - LAG(recovered_count)     OVER (ORDER BY day) AS recovered_count_delta,
    recovered_inr_major - LAG(recovered_inr_major) OVER (ORDER BY day) AS recovered_inr_major_delta
  FROM metrics_daily
 ORDER BY day DESC;

