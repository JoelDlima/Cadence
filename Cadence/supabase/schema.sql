-- ============================================================
-- Cadence Supabase mirror schema (Phase 4, secure version).
-- Run ONCE via the Supabase Management API or the SQL Editor.
-- ============================================================
-- This is the source of truth for the cloud-mirror tables.
-- Supabase's PostgREST auto-discovers the three tables, and the
-- service_role key (in `Cadence/.env` as SUPABASE_SERVICE_KEY)
-- POSTs to them with the `Prefer: resolution=merge-duplicates`
-- header for upsert behavior.
--
-- SECURITY: this schema REVOKEs all privileges from anon and
-- authenticated roles, GRANTS only to service_role, and ENABLEs
-- Row Level Security on every table with NO policies. That means
-- the anon and authenticated roles are blocked at the privilege
-- layer (REVOKE) AND the row layer (RLS deny-by-default). Only
-- the service_role bypasses RLS and can read or write. This is
-- the right posture for a backend mirror: external readers do not
-- exist.

-- ------------------------------------------------------------
-- 1. webhook_inbox
-- Razorpay webhooks land here first (via the Supabase Edge
-- Function) so the laptop-behind-NAT can poll them down through
-- the same gateway the FastAPI app exposes directly. The local
-- engine processes each row exactly once.
-- ------------------------------------------------------------
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
CREATE INDEX IF NOT EXISTS idx_webhook_inbox_event_id
    ON webhook_inbox (event_id);

-- ------------------------------------------------------------
-- 2. journeys_mirror
-- One row per recovery journey, mirrored one-way from the local
-- SQLite `journeys` table. Read by anyone with the service_role
-- key (i.e. the FastAPI app's /api/cloud/status endpoint and any
-- future dashboard). Mirror of the local DB; the local DB
-- remains the source of truth.
-- ------------------------------------------------------------
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
    updated_at       TIMESTAMPTZ NOT NULL,
    mirrored_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_journeys_mirror_state
    ON journeys_mirror (state);
CREATE INDEX IF NOT EXISTS idx_journeys_mirror_updated
    ON journeys_mirror (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_journeys_mirror_customer
    ON journeys_mirror (customer_id);

-- ------------------------------------------------------------
-- 3. metrics_daily
-- One row per day with the headline KPIs. Upserted by the local
-- worker every 30 seconds.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metrics_daily (
    day                  DATE PRIMARY KEY,
    journeys_opened      INTEGER NOT NULL DEFAULT 0,
    recovered_count      INTEGER NOT NULL DEFAULT 0,
    recovered_inr_major  NUMERIC(14, 2) NOT NULL DEFAULT 0,
    violations           INTEGER NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_metrics_daily_updated
    ON metrics_daily (updated_at DESC);

-- ------------------------------------------------------------
-- 4. Privileges: ONLY service_role can read/write. anon and
-- authenticated get NOTHING. (Service_role is set as the
-- `BYPASSRLS` role on Supabase, so it reads/writes regardless
-- of RLS being enabled.)
-- ------------------------------------------------------------
REVOKE ALL ON TABLE webhook_inbox    FROM anon, authenticated;
REVOKE ALL ON TABLE journeys_mirror  FROM anon, authenticated;
REVOKE ALL ON TABLE metrics_daily     FROM anon, authenticated;
GRANT  ALL ON TABLE webhook_inbox    TO service_role;
GRANT  ALL ON TABLE journeys_mirror  TO service_role;
GRANT  ALL ON TABLE metrics_daily     TO service_role;

-- ------------------------------------------------------------
-- 5. Row Level Security: deny all to anon and authenticated;
-- service_role bypasses.
-- ------------------------------------------------------------
ALTER TABLE webhook_inbox    ENABLE ROW LEVEL SECURITY;
ALTER TABLE journeys_mirror  ENABLE ROW LEVEL SECURITY;
ALTER TABLE metrics_daily     ENABLE ROW LEVEL SECURITY;
-- No policies => only service_role bypasses RLS and can read/write.
