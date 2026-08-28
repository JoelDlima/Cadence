# Supabase — Cadence cloud components (Phase 4)

Two roles: (1) **public webhook ingress** — Razorpay cannot reach a laptop
behind NAT, so webhooks hit the `revive-ingest` Edge Function, which verifies
HMAC-SHA256 over the raw body and stages payloads in `webhook_inbox`; our
local poller drains it. (2) **cloud mirror** — `journeys_mirror` +
`metrics_daily` for read-side dashboards. Service keys stay server-side only;
the console never talks to Supabase directly.

Cadence runs fully **offline-first**. None of this is required for the demo.
Add the keys only when you want a real (test-mode) cloud mirror.

## 1. Create the Supabase project

1. Sign up at https://supabase.com/dashboard (free tier, no card required).
2. Click **New project**. Pick a region close to India (`ap-south-1`
   Mumbai is the closest in Aug 2026). Choose a strong database password.
3. Wait ~2 minutes for provisioning. The free tier ships with 500 MB Postgres,
   50k MAU, and PostgREST auto-configured.

## 2. Apply the schema

The schema file is `main/supabase/schema.sql`. It creates four tables with
**RLS enabled and NO policies** — the only role that can read or write is
`service_role`, which is exactly the right posture for a backend mirror.

```bash
# From the Supabase dashboard
#   SQL Editor -> New query -> paste main/supabase/schema.sql -> Run
```

Or via CLI:

```bash
supabase db push --db-url "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
```

Tables created:

- `webhook_inbox` — staging for Razorpay deliveries (consumed by the local
  engine; never read by anyone else).
- `journeys_mirror` — one row per recovery journey, mirrored every 30s.
- `metrics_daily` — one row per day with the headline KPIs.
- `chaos_drill_runs` — optional; useful if you want a leaderboard of chaos
  drill results in the cloud.

## 3. Get the service role key

Settings → API → `service_role` key (the "secret" key). Copy it into
`main/.env`:

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>
CLOUD_SYNC_ENABLED=true
```

Restart the FastAPI app. The `/api/cloud/status` endpoint now reports
`sync_state: online` (or `error` with the last error message).

## 4. Deploy the Edge Function (optional, keyless-safe)

Only needed if Razorpay needs a public URL to reach your laptop. If your
dev box has a public address, you can skip this entirely and point Razorpay
directly at the FastAPI webhook endpoint (`/webhooks/razorpay`).

```bash
supabase functions deploy revive-ingest
supabase secrets set SUPABASE_URL=https://<project-ref>.supabase.co
supabase secrets set SUPABASE_SERVICE_ROLE_KEY=<service_role key>
supabase secrets set RAZORPAY_WEBHOOK_SECRET=<same value as local RZP_WEBHOOK_SECRET>
```

Razorpay Dashboard → Accounts & Settings → Webhooks → Add New Webhook:

- **URL**: `https://<project-ref>.supabase.co/functions/v1/revive-ingest`
- **Secret**: same value as `RZP_WEBHOOK_SECRET`
- **Events**: `subscription.pending`, `subscription.halted`, `payment.failed`, `payment.captured`

The local poller (`SupabaseInboxPoller`) drains the inbox every 2s. Each row
runs through the same gateway code the direct webhook uses.

## 5. Verify the mirror is working

With `CLOUD_SYNC_ENABLED=true` and both keys set:

```bash
curl -s http://localhost:8000/api/cloud/status | python -m json.tool
```

Should show `"sync_state": "online"`, a recent `last_journeys_sync_at`, and
`last_journeys_pushed > 0`. Then in Supabase Studio, Table Editor →
`journeys_mirror` should show your seeded journey.

If you see `"sync_state": "error"`, check `main/logs/api.err` for the HTTP
status code from the PostgREST call. Most common causes:

- Wrong service key (rotated; copy from Settings → API again).
- RLS policy added by accident (the file is deny-all; no policies = good).
- CORS / network: the FastAPI server can't reach `https://<ref>.supabase.co`.
  Check `curl -v $SUPABASE_URL/rest/v1/` from the same machine.

## 6. Why Supabase (and not Turso, Neon, D1, etc.)?

A 2026 research summary is in `main/docs/cloud-mirror.md`. Short version:

- **500 MB / 50k MAU / 2 projects** on the free tier is 1000× over-provision for
  <1k rows.
- **PostgREST + Supabase Dashboard** is the most familiar read-side
  interface for a hackathon judge in 2026.
- **1-week auto-pause** is fine for a 2-day demo (unpause is one click).
- **Turso / Neon / D1** are credible alternatives; we kept Supabase because
  the read-side ergonomics, the audience familiarity, and the migration cost
  made the switch not worth it at hackathon scope. The architecture doc
  explains the reasoning and the planned migration target if Cadence
  graduates past demo.
