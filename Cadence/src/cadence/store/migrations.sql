-- Cadence schema v1: event store, projections, durable queue, policy tables.
-- All timestamps are ISO-8601 UTC strings (canonical via clock.utc_iso).

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Append-only event log. hash = sha256(prev_hash || canonical(event minus hash)).
CREATE TABLE IF NOT EXISTS events (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL UNIQUE,
    occurred_at    TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    type           TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id   TEXT NOT NULL,
    payload        TEXT NOT NULL,
    prev_hash      TEXT NOT NULL,
    hash           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_agg ON events(aggregate_type, aggregate_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, seq);

-- Webhook idempotency: Razorpay retries deliveries; we must accept exactly once.
CREATE TABLE IF NOT EXISTS webhook_dedupe (
    dedupe_key    TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL
);

-- Read model / projection of recovery journeys. Rebuildable from events.
CREATE TABLE IF NOT EXISTS journeys (
    journey_id       TEXT PRIMARY KEY,
    subscription_id  TEXT NOT NULL UNIQUE,
    customer_id      TEXT NOT NULL,
    state            TEXT NOT NULL,
    failure_code     TEXT,
    root_cause       TEXT,
    classify_source  TEXT,
    amount_minor     INTEGER,
    currency         TEXT NOT NULL DEFAULT 'INR',
    attempts_used    INTEGER NOT NULL DEFAULT 0,
    touches_used     INTEGER NOT NULL DEFAULT 0,
    window_started_at TEXT,
    opened_at        TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    closed_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_journeys_state ON journeys(state);

-- Durable work queue + timers in one table (SQLite-as-queue pattern).
-- available_at in the future == timer; worker claims due rows atomically.
CREATE TABLE IF NOT EXISTS task_queue (
    task_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE,
    task_type       TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    available_at    TEXT NOT NULL,
    claimed_at      TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    last_error      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_due ON task_queue(status, available_at);

-- Rule F cost cap: hard daily ceiling on LLM requests, tracked server-side.
CREATE TABLE IF NOT EXISTS llm_spend (
    day      TEXT NOT NULL,
    provider TEXT NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider)
);

CREATE TABLE IF NOT EXISTS system_flags (
    flag       TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dnd_list (
    customer_id TEXT PRIMARY KEY,
    reason      TEXT NOT NULL,
    added_at    TEXT NOT NULL
);
