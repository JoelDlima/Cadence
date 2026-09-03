-- PHASE 4 (dashboard revamp): cloud mirror of every Razorpay payment link
-- Cadence creates, plus every lifecycle transition it drives.
--
-- Written by src/cadence/cloud/plink_mirror.py through PostgREST with the
-- service_role key. One-way: local SQLite + the hash chain remain the source
-- of truth; this table exists so the payment-link lifecycle is visible live in
-- the Supabase table editor during a demo.
--
-- Run once in Supabase Studio -> SQL Editor (idempotent, safe to re-run).

CREATE TABLE IF NOT EXISTS cadence_payment_links (
    id               BIGSERIAL PRIMARY KEY,
    plink_id         TEXT UNIQUE NOT NULL,          -- Razorpay plink_XXXX (upsert key)
    journey_id       TEXT,                          -- Cadence journey that owns the link
    subscription_id  TEXT,
    customer_id      TEXT,                          -- Razorpay cust_XXXX
    amount_minor     BIGINT,                        -- paise; INR 499.00 -> 49900
    currency         TEXT DEFAULT 'INR',
    status           TEXT DEFAULT 'created',        -- created|paid|partially_paid|cancelled|expired
    short_url        TEXT,
    reference_id     TEXT,                          -- '<journey_id>:<attempt_no>'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Append-only trail of transitions: [{at, event_type, status, payload}, ...]
    lifecycle_events JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_cadence_payment_links_updated
    ON cadence_payment_links (last_updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_cadence_payment_links_journey
    ON cadence_payment_links (journey_id);
CREATE INDEX IF NOT EXISTS idx_cadence_payment_links_status
    ON cadence_payment_links (status);

-- Deny-all by default; only service_role bypasses RLS. The SPA never talks to
-- Supabase directly -- it reads GET /api/cloud/plinks on the engine instead.
ALTER TABLE cadence_payment_links ENABLE ROW LEVEL SECURITY;
