# Cadence — Autonomous Revenue Defense for Indian Subscriptions

> **Razorpay AI Buildathon 2026 · Track 3 (AI Revenue Recovery)**
> Cadence detects failed subscription auto-debits, figures out *why* each one
> failed, and wins the money back — within RBI and NPCI rules, with a tamper-evident
> audit trail, and with measured rupees recovered across a reproducible batch.

---

## What Cadence is, in plain English

When a customer's UPI AutoPay or card e-mandate fails, that payment quietly
leaves the merchant's books forever. Most Indian recovery tools react with blind
retries and spam-style WhatsApp messages, often at 2 AM, often violating the
bank's quiet-hours rules. Cadence does the opposite:

- **A deterministic engine** reads the failure and decides what to do based on
  the exact Razorpay error code. Known codes are handled in **0 AI tokens**.
- **A Policy Guardian** checks every action against RBI and NPCI rules before
  it runs. It can veto anything illegal — including anything an LLM proposes.
- **The LLM** is only consulted for genuinely ambiguous cases. Even then, it can
  only choose from a fixed legal menu.
- **Every event** is written to a hash-chained SQLite log. Tampering with any
  row breaks the chain visibly.
- **An MCP server** lets any AI agent (Claude Desktop, Cursor, VS Code, …) inspect
  recovery operations in real time. Read-only, no write tools.

The result, on a seeded 500-subscriber batch calibrated to published Indian
failure rates:

| Metric | Naive dunning | Cadence |
|---|---|---|
| Revenue recovered | ₹113,311 (37.8%) | **₹166,228 (54.4%)** |
| Uplift over naive | — | **+43.9%** (India average: 20–35%) |
| Customer contacts per recovery | 8.22 | **0.64** |
| Compliance violations | — | **0** (Guardian vetoes enforce every cap) |
| LLM tokens spent on the batch | — | **0** (the fast path handled it all) |

Same seed → byte-identical report. Run it yourself:

```bash
cd main
pip install -e ".[dev]"
python scripts/run_eval.py        # writes docs/eval-report.md
python scripts/chaos_drills.py    # 4/4 PASS or it tells you why not
python -m uvicorn revive.api.app:app --port 8000
```

---

## Run it in 30 seconds, zero API keys

Cadence runs fully keyless in DEMO mode. Every external dependency has a
deterministic offline simulator, so a fresh clone works without a Razorpay
account, a Supabase project, an LLM key, or a Resend key.

```bash
# One-time
cd main
pip install -e ".[dev]"

# Daily driver — bring up API + SPA together
python scripts/dev.sh                  # bash  → API on :8000, SPA on :3000
powershell -ExecutionPolicy Bypass -File main\scripts\dev.ps1   # Windows

# Or run each half manually
python -m uvicorn revive.api.app:app --port 8000   # API
cd frontend && npm install && npm run dev        # SPA
# Open http://localhost:3000

# Other entrypoints
python scripts/seed.py                 # one synthetic failure, prints the journey
python -m pytest tests -q                # 282 tests
python scripts/run_mcp.py               # stdio MCP server for Claude Desktop
```

To switch from DEMO to LIVE, fill `main/.env` with the real Razorpay
test-mode keys, Supabase service key, Resend key, and any LLM key. The
`/api/status` endpoint reports the current mode and which keys are
configured; the UI renders a `DEMO` or `LIVE` badge from it.

---

## The architecture, in one line

**Deterministic spine, probabilistic edges.** Rules and state machines own
money logic. The LLM only proposes. A pure-code Policy Guardian can always
veto.

```
Razorpay (test mode) ──webhooks──► Supabase Edge Function (public HMAC ingress)
                                          │ webhook_inbox
   local engine ◄────── poller ─────────────┘
        ▼
  EVENT-SOURCED CORE (SQLite, hash-chained audit)
        ▼
  CLASSIFY (real Razorpay/UPI error codes → root cause)
        ▼ fast path: zero AI tokens for known codes
  POLICY GUARDIAN (pure-code veto) — ≤3 touches/14d, quiet hours
    21:00–09:00 IST, DND, hard-decline stop, RBI 24h pre-debit notice,
    amount-tier approvals, kill switch
        ▼ unclassifiable codes only → LLM (Gemini→Groq→OpenRouter→Ollama)
  EXECUTORS — Razorpay Payment Links (test mode) · retries ·
    WhatsApp/email channels
        ▼ durable timers wake journeys at payday / cooldown / promise-to-pay
  SIMULATOR + EVAL HARNESS → ₹ recovered vs naive baseline
```

The FastAPI app runs its own background worker. Post a webhook and the journey
opens, classifies, and schedules recovery with no companion script. Kill the
process mid-journey and restart: the journey resumes exactly where it stopped,
replayable decision-by-decision from the event log.

---

## What is real vs simulated (honesty table)

| Real | Simulated (deliberately, behind swappable interfaces) |
|---|---|
| Razorpay rails, webhook security, Payment Links (test mode) | Mandate re-debits (no public NPCI merchant API exists) |
| LLM planner calls, budget accounting | WhatsApp channel (Business API needs company verification) |
| Email via Resend (when RESEND_API_KEY set) | Customer reply outcomes (calibrated simulator) |
| Event engine, Guardian, timers, audit chain | NPCI peak-hold phantom-failure guard (calendar only) |

Everything simulated is intentionally behind a swappable interface and is
labelled in code. Every integration degrades to a simulator when keys are
absent, so CI and the demo never break.

---

## The 8 read-only MCP tools

Cadence ships as an MCP server so any AI agent can inspect the recovery loop.
The server is built on the official `mcp` Python SDK v1.x (the same SDK the
Razorpay and Stripe MCP servers use). Eight tools, all read-only, no write
surface:

| Tool | What it returns |
|---|---|
| `revive_list_journeys` | Paginated list of recovery journeys |
| `revive_get_timeline` | Hash-chained event timeline for one journey |
| `revive_get_metrics` | Recovered INR, journeys by state, LLM requests, Guardian veto count |
| `revive_list_dead_letters` | Tasks that exhausted retries |
| `revive_get_status` | DEMO/LIVE mode and which keys are present |
| `revive_get_attention` | Journeys flagged for human review, high value, or bank-outage pause |
| `revive_audit_verify` | Hash-chain integrity check (detects tamper) |
| `revive_get_guardian_stats` | Veto counts grouped by reason |

Point Claude Desktop, Cursor, or VS Code at `scripts/run_mcp.py`. Full
config snippets and security posture in [`docs/mcp-integration.md`](docs/mcp-integration.md).

---

## Repository map

- `main/src/revive/` — engine, classifier, Guardian, agents, executors, worker, cloud, sim, api, MCP server
- `main/docs/` — [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) (one-page diagram), [`eval-report.md`](docs/eval-report.md) + metrics, [`evidence-pack.md`](docs/evidence-pack.md) (13 primary sources), [`mcp-integration.md`](docs/mcp-integration.md), [`cloud-mirror.md`](docs/cloud-mirror.md), [`PITCH-VIDEO.md`](docs/PITCH-VIDEO.md) (5-min script), [`PITCH-DECK.md`](docs/PITCH-DECK.md) (slide deck), [`PITCH-GIF.md`](docs/PITCH-GIF.md) (hero GIF capture), [`APPLICATION.md`](docs/APPLICATION.md) (form answer cheat-sheet), pre-launch audit, Research-OS set
- `main/JOURNAL.md` — every real bug, decision, and escape, dated
- `main/supabase/` — schema (RLS-deny-all, 4 tables) + edge-function webhook ingress (optional; keyless works)
- `main/scripts/` — dev runbook, seed, demo, eval, chaos drills, MCP server
- `main/frontend/` — Vite + React 19 + Tailwind v4 SPA (DEMO/LIVE badge, all numbers live)

---

## Status

**284 tests · 4/4 chaos drills · +43.9% measured uplift · 0 violations · 8 MCP
tools live · 8 backend endpoints serving the SPA · Supabase cloud mirror
with live status · all 8 frontend KPIs wired to the real API (no hard-coded
numbers).** The single honest gap is: the Razorpay live-mode wiring, which
is gated on real test-mode keys (keys coming in 2 days). Everything else
works keyless today.

---

## Phase history (this build)

Each phase is a self-contained commit. The README grew with them.

**Phase 0 — Repo hygiene.** Deleted the old vanilla console, sibling builds,
and capture scripts. Added a one-command dev runbook (`scripts/dev.sh` /
`dev.ps1`), a keyless seed script, MIT LICENSE, and a per-package `.gitignore`.

**Phase 1 — Brand + token cleanup.** Renamed user-facing surfaces from
"Revive" to "Cadence" (the Python package kept its `revive` internal name
to avoid a sweeping refactor). Repaired the frontend token system: deleted
`App.css` and `tailwind.config.js` (Tailwind v3 dead code), added the
`@theme` block in `index.css` that the SPA actually uses.

**Phase 2 — Real-data UI.** Every hard-coded number in the React SPA is
gone. Eight new backend endpoints (`/api/status`, `/api/attention`,
`/api/banks`, `/api/audit/verify`, `/api/llm-spend`, `/api/guardian-stats`,
`/api/eval-summary`, `/api/chaos/{id}/run`, `/api/test/inject`) feed the UI
with live data. The chaos drills actually run on the server instead of
returning canned `setTimeout(900)` strings. The Pay Portal calls a real
endpoint. A DEMO/LIVE badge in the sidebar tells judges which mode the
system is in.

**Phase 3 — MCP server upgrade.** Migrated the MCP server from hand-rolled
JSON-RPC to the official `mcp` Python SDK v1.x (the same SDK the Razorpay
and Stripe MCP servers use). Expanded from 4 to **8 read-only tools**:
`revive_list_journeys`, `revive_get_timeline`, `revive_get_metrics`,
`revive_list_dead_letters`, `revive_get_status`, `revive_get_attention`,
`revive_audit_verify`, `revive_get_guardian_stats`. The server is
registered on Claude Desktop, Cursor, and VS Code via a single
`scripts/run_mcp.py` entry point. Full integration guide in
`docs/mcp-integration.md`.

**Phase 4 — Cloud mirror (keyless-friendly).** Cadence now ships a proper
cloud mirror, not a stub. The schema is committed at
`main/supabase/schema.sql` and creates four tables (`webhook_inbox`,
`journeys_mirror`, `metrics_daily`, `chaos_drill_runs`) with RLS
deny-all-by-default. A new `/api/cloud/status` endpoint reports the
connection state (offline / online / error, last sync time, last error).
The React sidebar shows a live "Cloud Mirror: ONLINE / OFFLINE / ERROR"
indicator next to the port number. We evaluated Turso (libSQL), Neon
(Postgres), Cloudflare D1, SQLite Cloud, and PGlite and kept Supabase —
full reasoning in `docs/cloud-mirror.md`. The plan: ship the demo
on Supabase; the planned migration target for post-hackathon is Turso.
Cadence still runs fully offline with zero keys; the mirror only
activates when `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are set.

**Phase 5 — Pitch assets.** The submission form asks for a 5-minute pitch
video. We could not record one in this environment, so the pitch
assets now include three deliverables:

- [`docs/PITCH-VIDEO.md`](docs/PITCH-VIDEO.md) — the 5-minute shot-by-shot
  script, optimised for Razorpay's 2026 fintech panel. Includes "what
  NOT to say" table and a recording budget.
- [`docs/PITCH-DECK.md`](docs/PITCH-DECK.md) — the same 5 minutes as a
  markdown slide deck. Paste slide 1 into the application form's free-text
  summary field if a video isn't possible.
- [`docs/PITCH-GIF.md`](docs/PITCH-GIF.md) — instructions for capturing the
  10-second silent hero GIF that goes at the top of this README. Uses OBS
  Studio + ScreenToGif on Windows, ffmpeg on macOS, or Playwright in CI.

The research for this phase confirmed: a public YouTube unlisted link is
the de-facto expected format (not Loom or MP4), and a hero GIF embedded
directly in the README is now standard for 2026 hackathon submissions.

---

*Your code speaks louder than your resume. Built during the night shift.*
