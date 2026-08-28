-- Revive Supabase schema (Phase E3). Run once in Supabase Studio SQL Editor.
-- Raw webhook payloads staged by the revive-ingest Edge Function; drained by
-- the local SupabaseInboxPoller.
create table webhook_inbox (
    id           uuid primary key default gen_random_uuid(),
    payload      jsonb not null,
    signature    text,
    processed    boolean not null default false,
    processed_at timestamptz,
    received_at  timestamptz not null default now()
);

-- Read-only mirror of local journey projections, for shared dashboards.
create table journeys_mirror (
    journey_id      text primary key,
    subscription_id text,
    customer_id     text,
    state           text,
    root_cause      text,
    classify_source text,
    amount_minor    bigint,
    attempts_used   int default 0,
    touches_used    int default 0,
    opened_at       timestamptz,
    updated_at      timestamptz
);

-- Daily rollups mirrored by CloudSync.sync_metrics().
create table metrics_daily (
    day                date primary key,
    journeys_opened    int default 0,
    recovered_count    int default 0,
    recovered_inr_major numeric default 0,
    violations         int default 0
);

alter table webhook_inbox enable row level security;
alter table journeys_mirror enable row level security;
alter table metrics_daily enable row level security;

-- NOTE: no policies are created on purpose => anon/authenticated roles are
-- denied all access; only service_role (our server-side keys) bypasses RLS.
