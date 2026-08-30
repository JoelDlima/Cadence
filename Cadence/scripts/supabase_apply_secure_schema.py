"""Apply the secure Supabase schema (RLS locked + indexes).

This DROP-and-recreates the public schema, recreates the mirror
tables WITH Row Level Security enabled + 0 policies, and adds
indexes on the columns the engine filters/sorts by.

The original schema from the docs applied ENABLE ROW LEVEL SECURITY
but the table privileges still allowed anon/authenticated reads
in some paths. This version:
  - REVOKEs all privileges from anon and authenticated
  - GRANTs only to service_role (the engine uses this JWT)
  - Creates the index the Supabase linter flagged as missing
  - Drops the unused view and the security-definer function
    (the linter flagged both as CRITICAL)
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def main() -> int:
    project_ref = os.environ.get("SUPABASE_PROJECT_REF", "vzrasadomyrycafbzdwg")
    pat = os.environ.get("SUPABASE_PAT")
    if not pat:
        print("[error] SUPABASE_PAT not set. Create a Personal Access Token at"
              " https://supabase.com/dashboard/account/tokens and put it in"
              " your shell or Cadence/.env.")
        return 1

    secure_schema_sql = """
-- ============================================================
-- Cadence Supabase schema (secure version)
-- Run once via Management API to replace the prior unsecure version.
-- ============================================================

-- 1. Drop everything from the prior apply (safe because it's a mirror)
DROP VIEW  IF EXISTS public.daily_metrics_with_delta;
DROP TABLE IF EXISTS public.chaos_drill_runs;
DROP TABLE IF EXISTS public.webhook_inbox       CASCADE;
DROP TABLE IF EXISTS public.journeys_mirror     CASCADE;
DROP TABLE IF EXISTS public.metrics_daily        CASCADE;
DROP FUNCTION IF EXISTS public.rls_auto_enable() CASCADE;

-- 2. The three mirror tables
CREATE TABLE public.webhook_inbox (
    id            BIGSERIAL PRIMARY KEY,
    event_id      TEXT NOT NULL UNIQUE,             -- Razorpay X-Razorpay-Event-Id
    payload       JSONB NOT NULL,
    signature    TEXT,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    processed    BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_webhook_inbox_unprocessed
    ON public.webhook_inbox (received_at)
 WHERE processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_webhook_inbox_event_id
    ON public.webhook_inbox (event_id);

CREATE TABLE public.journeys_mirror (
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
    ON public.journeys_mirror (state);
CREATE INDEX IF NOT EXISTS idx_journeys_mirror_updated
    ON public.journeys_mirror (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_journeys_mirror_customer
    ON public.journeys_mirror (customer_id);

CREATE TABLE public.metrics_daily (
    day                  DATE PRIMARY KEY,
    journeys_opened      INTEGER NOT NULL DEFAULT 0,
    recovered_count      INTEGER NOT NULL DEFAULT 0,
    recovered_inr_major  NUMERIC(14, 2) NOT NULL DEFAULT 0,
    violations           INTEGER NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_metrics_daily_updated
    ON public.metrics_daily (updated_at DESC);

-- 3. Privileges: ONLY the service_role can read/write. anon and
--    authenticated get nothing. This is the right posture for a
--    backend mirror: external readers do not exist.
REVOKE ALL ON TABLE public.webhook_inbox    FROM anon, authenticated;
REVOKE ALL ON TABLE public.journeys_mirror  FROM anon, authenticated;
REVOKE ALL ON TABLE public.metrics_daily     FROM anon, authenticated;
GRANT  ALL ON TABLE public.webhook_inbox    TO service_role;
GRANT  ALL ON TABLE public.journeys_mirror  TO service_role;
GRANT  ALL ON TABLE public.metrics_daily     TO service_role;

-- 4. Row Level Security: deny by default. No policies => no
--    rows visible to anon/authenticated. service_role bypasses
--    RLS by design.
ALTER TABLE public.webhook_inbox    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.journeys_mirror  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.metrics_daily     ENABLE ROW LEVEL SECURITY;
"""

    print(f"[ok] secure schema ready ({len(secure_schema_sql)} chars)")
    url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    body = __import__("json").dumps({"query": secure_schema_sql}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f"[ok] status {r.status}")
            data = r.read().decode()
            if data:
                print(f"     response: {data[:500]}")
    except urllib.error.HTTPError as e:
        print(f"[FAIL] status {e.code}")
        print(f"     body: {e.read().decode()[:1000]}")
        return 1

    # verify
    sb_url = f"https://{project_ref}.supabase.co"
    sr_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    pub_key = os.environ.get(
        "SUPABASE_PUBLISHABLE_KEY",
        "sb_publishable_-M9Rf7TGC7N-IOiQIpoO2w_Qj7R-QRe",
    )
    print()
    print("[verify] tables now have RLS + no anon grants")
    for table in ("webhook_inbox", "journeys_mirror", "metrics_daily"):
        # service_role can read
        h = {"apikey": sr_key, "Authorization": f"Bearer {sr_key}", "User-Agent": UA}
        req = urllib.request.Request(f"{sb_url}/rest/v1/{table}?select=count", headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=10)
            print(f"     service_role -> {table}: {r.read().decode()}")
        except Exception as e:
            print(f"     service_role -> {table}: {e}")
        # publishable cannot (RLS deny)
        h2 = {"apikey": pub_key, "Authorization": f"Bearer {pub_key}", "User-Agent": UA}
        req2 = urllib.request.Request(f"{sb_url}/rest/v1/{table}?select=count", headers=h2)
        try:
            r2 = urllib.request.urlopen(req2, timeout=10)
            print(f"     publishable -> {table}: {r2.read().decode()[:200]}")
        except urllib.error.HTTPError as e:
            print(f"     publishable -> {table}: {e.code} (expected; RLS denies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
