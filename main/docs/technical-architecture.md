# Technical Architecture

Mode: Hackathon Sprint · Research date: 2026-08-22 · Full depth

## Overview

Single-process Python service (FastAPI + background worker loops) over an embedded
SQLite store in WAL mode. Public ingress delegated to a Supabase Edge Function. No BaaS
in the critical path; cloud is mirror-only.

## Components and data flow

```
Razorpay --webhooks--> Edge Function revive-ingest (HMAC verify) --> webhook_inbox
local poller --> gateway processing (idempotent) --> events (hash-chained append-only)
     --> RecoveryEngine (classify -> guardian -> schedule) --> task_queue rows
Worker bus (atomic claim, backoff, DLQ) --> Dispatcher --> Razorpay APIs / channels
Timers = future-dated queue rows; outcome checks loop failures back with cool-off
CloudSync upserts projections to Supabase Postgres for dashboards (env-gated)
Console (vanilla JS) polls local API only
```

## Key decisions

| Decision | Choice | Rationale | Production analogue |
|---|---|---|---|
| Source of truth | SQLite event log, hash-chained sha256(prev+canonical) | tamper-evident audit; replayable; zero ops | Kafka + event store |
| Queue + timers | one task_queue table; UPDATE..RETURNING atomic claim | durable timers without infra; crash-safe | Redis Streams / Temporal |
| Decisions | rules-first classifier; deterministic fast path; LLM only ambiguous | measurable AI judgment; cost bounded | production dual-process agents |
| Governance | Policy Guardian pure functions between proposal and action | machine-checkable compliance incl RBI e-mandate 24h notice, non-peak retries | policy-as-code |
| Ingress | Supabase Edge Function public URL | laptop has no public endpoint; 5s ack requirement met | webhook relay |
| Secrets | env vars server-side only (.env gitignored); Supabase service key never leaves server/function; no client-bundled keys anywhere | Rule A/Guardrail 2 | secret manager |
| Auth | single-operator local tool; kill switch + HMAC at the only public surface (edge function) | scope-honest for hackathon | SSO post-event |

## Observability

Structured logging (no prints); the event store itself is the audit trail (`verify_chain`);
`llm_spend` table tracks provider usage daily; eval report auto-generated from runs.
Sentry deferred (Phase F decision).

## Scaling notes

SQLite handles demo scale trivially. Path documented, not built: swap `task_queue` for
Redis Streams consumer groups or Temporal workflows; keep engine/handlers unchanged
(they depend on repo interfaces only). Postgres via Supabase already provisioned as the
mirror target.

## Fallback architecture

Every external dependency degrades: keys absent -> simulated Razorpay + mock channels;
LLM chain exhausted/capped -> template fallback path (planner returns None, fast path or
human review); Supabase down -> offline loop intact. CI runs fully keyless (96 tests).

## Third-party dependencies (pinned)

fastapi 0.115.12, uvicorn 0.34.0, httpx 0.28.1, pydantic 2.11.3, python-dotenv 1.1.0,
tzdata 2025.2. Dev: pytest, pytest-cov, ruff, black.
