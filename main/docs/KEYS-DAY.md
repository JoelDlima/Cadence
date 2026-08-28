# Cadence — Keys Day

**The fastest possible path from "fresh clone" to "everything LIVE".**

This document is the runbook for the day you drop Razorpay, Supabase,
Resend, and LLM keys into `main/.env`. It is the inverse of `docs/PITCH-VIDEO.md`'s
opening line ("zero keys needed to run it"): same repo, same tests, but
the `DEMO` badge in the sidebar flips to `LIVE` once any key is set.

The Cadence architecture is **keyless-first, live-on-demand**. Every
external dependency has a deterministic offline simulator. Setting
keys in `main/.env` activates the live code path for that dependency;
the keyless path is unchanged. You do not have to set them all to
start; you can set them one at a time and watch the UI badge change.

---

## 0. Verify the baseline (always do this first)

```bash
cd main
pip install -e ".[dev]"

# Start keyless, confirm DEMO mode everywhere
python -m uvicorn revive.api.app:app --port 8000 &
cd ../main/frontend && npm install && npm run dev &

# In another terminal
curl -s http://localhost:8000/api/status | python -m json.tool
# Expected: {"mode": "DEMO", "razorpay_keys_present": false, ...}

python scripts/live_check.py
# Expected output: "Cadence live-check" header; all rows say SIMULATED.
```

If `/api/status` does not return `mode: "DEMO"`, stop. The keyless
baseline is broken and adding keys will not fix it.

---

## 1. Razorpay (test mode)

**What flips to LIVE:** the `/api/pay/{id}/link` endpoint will start
calling the real Razorpay Payment Links API instead of the simulator.
`/api/test/inject` will accept real webhooks. `/api/status` reports
`razorpay_keys_present: true, mode: LIVE`.

**Where to get keys:** Razorpay Dashboard → Settings → API Keys → Test Mode.
You'll see `rzp_test_...` and `secret_...`. Do **not** use live keys
during the buildathon.

**What to put in `main/.env`:**

```
RZP_KEY_ID=rzp_test_xxxxxxxx
RZP_KEY_SECRET=secret_xxxxxxxxxxxx
RZP_WEBHOOK_SECRET=<random 32+ char string>
```

The webhook secret is the one Razorpay signs with. Use any random string
(openssl rand -hex 32). The Edge Function in `main/supabase/functions/revive-ingest/index.ts`
must use the same value as its `RAZORPAY_WEBHOOK_SECRET` env var.

**How to verify:**

```bash
# Restart the API
python scripts/live_check.py
# Expected: Razorpay API   LIVE         auth OK, test-mode REST reachable
#           Webhook secret SET          64 chars; must equal Supabase secret

curl -s http://localhost:8000/api/status | python -m json.tool
# Expected: mode == "LIVE", razorpay_keys_present == true
```

**If it says 401:** you pasted the live key, not the test key. Get the
test key from the Razorpay Dashboard.

---

## 2. LLM provider (pick one)

**What flips to LIVE:** when an unclassifiable error code reaches the
planner, it can call a real LLM. The deterministic fast path doesn't
touch the LLM (the eval has 0 LLM tokens on standard codes; the
planner is only consulted for genuinely ambiguous errors).

**Cheapest option (no card):** Groq. Sign up at https://console.groq.com/keys.
Free tier: ~30 RPM, ~14,400 req/day.

**Backup option (no card):** OpenRouter's `meta-llama/llama-3.3-70b-instruct:free`
model. Sign up at https://openrouter.ai/keys.

**What to put in `main/.env` (Groq):**

```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxx
LLM_MODEL_GROQ=llama-3.3-70b-versatile
```

Or for OpenRouter:

```
OPENROUTER_API_KEY=sk-or-xxxxxxxx
LLM_MODEL_OPENROUTER=meta-llama/llama-3.3-70b-instruct:free
```

**How to verify:**

```bash
python scripts/live_check.py
# Expected: LLM planner  LIVE         groq (llama-3.3-70b-versatile) answered

curl -s http://localhost:8000/api/status | python -m json.tool
# Expected: llm_keys_present == true, mode == "LIVE"
```

**A note on Gemini:** the free tier for `gemini-2.0-flash` was tightened
in late 2025 (~250 RPD worst case, source disagreement across
documentation). We default to Groq as the primary because it has the
most reliable free tier in 2026. Add Gemini as a second provider if
you want belt-and-suspenders fallback.

---

## 3. Email (Resend)

**What flips to LIVE:** when the engine dispatches an email nudge, it
calls the real Resend API. Without this, email sends are simulated
(logged only). The PayPortalView's "Send email" button actually
delivers.

**Where to get key:** https://resend.com/api-keys (free tier: 3,000
emails/month, 100/day).

**What to put in `main/.env`:**

```
RESEND_API_KEY=re_xxxxxxxxxxxx
EMAIL_FROM=cadence@your-verified-domain.com
```

You must verify the `EMAIL_FROM` domain in the Resend dashboard
before sending; otherwise emails are rejected.

**How to verify:**

```bash
python scripts/live_check.py
# Expected: Email (Resend)  LIVE         from cadence@...

# Manual: trigger an email via the SPA's Pay Portal, check your inbox.
```

---

## 4. Supabase cloud mirror

**What flips to LIVE:** every 30 s, the worker thread upserts the
local journeys table and a daily metrics row to your Supabase
project. `/api/cloud/status` reports `sync_state: online` and a recent
`last_journeys_sync_at` timestamp. The sidebar's Cloud Mirror
indicator flips to green.

**Where to get keys:** https://supabase.com/dashboard (free tier: 500 MB
Postgres, 50k MAU, no card).

**One-time setup (5 minutes):**

1. Create a Supabase project, choose Mumbai region if available.
2. In SQL Editor → New query → paste the entire contents of
   `main/supabase/schema.sql` → Run. This creates 4 tables with
   RLS enabled and zero policies (only the service role bypasses).
3. In Settings → API, copy the Project URL and the `service_role`
   secret (click Reveal). The service role key is **secret**; never
   commit it.

**What to put in `main/.env`:**

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOi...
CLOUD_SYNC_ENABLED=true
```

**How to verify:**

```bash
python scripts/live_check.py
# Expected: Supabase     LIVE         inbox reachable at https://...

# Wait 30s, then:
curl -s http://localhost:8000/api/cloud/status | python -m json.tool
# Expected: enabled: true, sync_state: online,
#           last_journeys_sync_at: <recent timestamp>,
#           last_journeys_pushed: 1+ (after seed)

# In Supabase Studio, Table Editor -> journeys_mirror:
# you should see your seeded journey row.
```

**If it says "error":** check `main/logs/api.err` for the HTTP status
from the PostgREST call. Most common cause: wrong service key
(rotated; copy from Settings → API again).

---

## 5. Verify the full LIVE state

After setting all four classes, run the demo loop end-to-end:

```bash
# In three terminals
python -m uvicorn revive.api.app:app --port 8000
cd ../main/frontend && npm run dev
# (in a third) python scripts/seed.py
```

Then in the SPA:
- **Sidebar:** `DEMO` badge → `LIVE`. `Cloud Mirror: OFFLINE` → `ONLINE`.
- **Testbench:** inject a webhook; the journey is processed, classified,
  scheduled. `/api/metrics` should show the new journey.
- **Pay Portal:** click Inject, the Pay Portal view (or `/pay/{id}`)
  shows a real Razorpay short URL.
- **MCP server:** `python scripts/run_mcp.py` works the same in DEMO
  and LIVE; the read-only data is the same shape.

---

## 6. The 30-second full LIVE checklist

```bash
# 1. Edit main/.env
cat main/.env
# RZP_KEY_ID=rzp_test_xxxx
# RZP_KEY_SECRET=secret_xxxx
# GROQ_API_KEY=gsk_xxxx
# RESEND_API_KEY=re_xxxx
# SUPABASE_URL=https://xxx.supabase.co
# SUPABASE_SERVICE_KEY=eyJ...
# CLOUD_SYNC_ENABLED=true
# (RZP_WEBHOOK_SECRET stays the same value as in supabase secrets)

# 2. Restart
pkill -f uvicorn 2>/dev/null
pkill -f "npm run dev" 2>/dev/null
cd main && python -m uvicorn revive.api.app:app --port 8000 &
cd frontend && npm run dev &

# 3. Confirm
python scripts/live_check.py
curl -s http://localhost:8000/api/status | python -m json.tool
curl -s http://localhost:8000/api/cloud/status | python -m json.tool
```

All four integration rows should say `LIVE`, the Supabase row should
say `online`, and the SPA sidebar should show two green dots. The
demo is now fully LIVE.

---

## 7. If something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/status` shows `mode: "DEMO"` after setting keys | `.env` not in the right place | File must be `main/.env`, not `main/main/.env` or `.env`. |
| Razorpay live-check returns 401 | You used live keys instead of test | Dashboard → API Keys → Test Mode |
| Razorpay live-check returns network error | No internet, or corporate proxy | Run from a machine with full outbound HTTPS |
| Groq live-check returns 401 | Wrong key format | Groq keys start with `gsk_` |
| Supabase status shows `error` | Wrong service key | Settings → API → service_role → copy the new one |
| Supabase status shows `error` after deploy | Schema not applied | Run `main/supabase/schema.sql` in SQL Editor |
| Email is sent but goes to spam | `EMAIL_FROM` not verified in Resend | Domains → Add domain → add DNS records |
| MCP server fails to start | `mcp` SDK not installed | `pip install -e ".[dev]"` re-runs the install with the dev deps |

If a fix isn't on this list, check the application log:
`main/logs/api.log` (uvicorn stdout) and `main/logs/api.err` (stderr).

---

## 8. To go back to DEMO

Comment out the keys in `main/.env` (or rename the file to `.env.live`
and rename `.env.example` to `.env`). Restart. The simulator path is
identical for every integration except Razorpay (which uses
`https://api.razorpay.com` only when `is_live`). Cadence never
deletes or corrupts local data when keys are removed; the next
restart reverts to keyless mode cleanly.

---

## 9. The single line that matters

The only line in this entire project that has to work the same in
DEMO and LIVE is `python scripts/live_check.py`. Run it after every
key change. If it says `LIVE` for a row, that integration is real.
If it says `SIMULATED`, the key is missing or wrong. The demo
contract is that **every number on the SPA is real** — either from a
real API call or from a deterministic simulator with the same
code path as the real call. There is no third option.
