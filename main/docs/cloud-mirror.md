# Cloud Mirror — Design and Alternatives

Cadence's local SQLite database is the system of record. The cloud mirror
exists to make recovery operations observable to anyone (judges, team
members, future dashboards) without giving them access to the laptop running
the FastAPI app. It is **read-side, one-way, optional**.

## What the mirror does

Every 30 seconds (configurable), a worker thread in the FastAPI app does
two PostgREST upserts against the configured cloud project:

```
POST {supabase_url}/rest/v1/journeys_mirror?on_conflict=journey_id
  (Prefer: resolution=merge-duplicates, return=minimal)
  body: [{journey_id, subscription_id, ..., mirrored_at}, ...]  (newest 100)

POST {supabase_url}/rest/v1/metrics_daily?on_conflict=day
  (Prefer: resolution=merge-duplicates, return=minimal)
  body: [{day, journeys_opened, recovered_count, recovered_inr_major, violations, updated_at}]
```

Both tables are RLS-deny-all by default. Only the `service_role` key
(server-side, never in the React SPA) can read or write. There is no
end-user read surface in this build.

## What the mirror does NOT do

- It does **not** store card numbers, VPAs, API keys, or any PCI scope.
- It does **not** accept writes from the outside.
- It does **not** replace the local SQLite DB. The local DB is the source
  of truth; the cloud mirror is a delayed (≤30s) read snapshot.
- It does **not** require any external service for the demo to run. The
  `/api/cloud/status` endpoint reports `sync_state: offline` with all
  timestamps null when no Supabase keys are set, and the entire stack
  keeps working keyless.

## Why Supabase, not Turso / Neon / D1 / R2 / PGlite (Aug 2026)

We evaluated the credible alternatives in late Aug 2026. Here is the
honest assessment.

| Option | Free tier | HTTP from Python | Verdict |
|---|---|---|---|
| **Supabase** (chosen) | 500 MB, 50k MAU, 2 projects, no card | PostgREST, `Prefer: resolution=merge-duplicates` | **Kept.** |
| Turso (libSQL) | 5 GB, 10M writes/mo, no card | `POST /v2/pipeline`, JSON SQL | **Strongest alternative.** Same SQLite dialect as the local DB; cleanest API. |
| Neon (Postgres) | 0.5 GB, 100 CU-hr/mo, no card | PostgREST-compatible Data API (beta) | **Acceptable.** Postgres schema translation is the only friction. |
| SQLite Cloud | no free, no cardless tier | proprietary REST | **Not recommended.** Fails the no-card requirement. |
| Cloudflare D1 | 5M rows read/day, 100k written/day, no card | Workers binding or REST for management only | **Not recommended for this use case.** No direct HTTP from a Python writer. |
| R2 + Workers | 10 GB storage, 1M writes/mo, $0 egress | S3-compatible API | **Not a primary mirror.** It's an object store, not a queryable DB. Useful as a *complement* (e.g., nightly snapshot to R2 for archival). |
| PGlite (WASM Postgres) | Apache 2.0, npm-only | none (in-process library) | **Not recommended.** It's a library, not a service. |

**Why we kept Supabase:**

1. **Audience.** Hackathon judges in 2026 recognize PostgREST. A Supabase
   dashboard sitting at `*.supabase.co` is something they have seen in
   dozens of other submissions; Turso's `POST /v2/pipeline` is novel and
   costs 30 seconds of context.
2. **Workload fit.** 500 MB / 50k MAU / 2 projects is 1000× over-provision
   for <1k rows across 3 tables. We are nowhere near any limit.
3. **Risk asymmetry.** The cost of staying on Supabase is $0 and zero
   migration work. The cost of switching to Turso to look "modern" is
   rewriting the mirror code (small) plus asking a judge to evaluate an
   unfamiliar stack under time pressure (real). Don't switch.
4. **The 1-week auto-pause** is fine for a 2-day hackathon demo. Unpause
   is one click in the Supabase dashboard.

**Planned migration target if Cadence graduates past demo:** Turso. Same
SQLite dialect means the local `journeys` table mirrors byte-for-byte. The
free tier is larger, the HTTP API is cleaner, and the embedded-replica
mode lets the laptop run a local read replica with no extra infra.

## Threat model

| Concern | Cadence's posture |
|---|---|
| Can a leaked Supabase URL leak data? | No — tables are RLS-deny-all. Only the `service_role` key (server-side) reads them. |
| Can a leaked `SUPABASE_SERVICE_KEY` leak data? | Yes — but it never leaves the server. It is in `main/.env` (gitignored) only. |
| Can a reader of the mirror write back? | No — `service_role` write is gated by the FastAPI process. |
| Can the local DB be tampered with? | The hash chain (`revive_audit_verify`) detects any row change within seconds. |
| Can a bad Razorpay webhook trigger an ungoverned action? | No — every webhook is HMAC-verified before it reaches the engine, and every action passes through the Policy Guardian. |

## Configuration

All four values go in `main/.env` (gitignored):

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>
CLOUD_SYNC_ENABLED=true
```

Leave any of them blank to stay in offline mode. `/api/cloud/status` reports
the current state.
