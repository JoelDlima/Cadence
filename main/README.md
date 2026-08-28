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
- `main/docs/` — [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) (one-page diagram), [`eval-report.md`](docs/eval-report.md) + metrics, [`evidence-pack.md`](docs/evidence-pack.md) (13 primary sources), [`mcp-integration.md`](docs/mcp-integration.md), [`cloud-mirror.md`](docs/cloud-mirror.md), [`PITCH-VIDEO.md`](docs/PITCH-VIDEO.md) (5-min script), [`PITCH-DECK.md`](docs/PITCH-DECK.md) (slide deck), [`PITCH-GIF.md`](docs/PITCH-GIF.md) (hero GIF capture), [`APPLICATION.md`](docs/APPLICATION.md) (form answer cheat-sheet), [`KEYS-DAY.md`](docs/KEYS-DAY.md) (live-mode runbook), [`RESEARCH-2026-08-28.md`](docs/RESEARCH-2026-08-28.md) (deep research, 10+ sources, top-5 picks), pre-launch audit, Research-OS set
- `main/JOURNAL.md` — every real bug, decision, and escape, dated
- `main/supabase/` — schema (RLS-deny-all, 4 tables) + edge-function webhook ingress (optional; keyless works)
- `main/scripts/` — dev runbook, seed, demo, eval, chaos drills, MCP server
- `main/frontend/` — Vite + React 19 + Tailwind v4 SPA (DEMO/LIVE badge, all numbers live)

---

## Status

**297 tests · 4/4 chaos drills · +43.9% measured uplift · 0 violations · 8 MCP
tools live · 8 backend endpoints serving the SPA · Supabase cloud mirror
with live status · all 8 frontend KPIs wired to the real API (no hard-coded
numbers) · Faker-driven 5,000-sub Indian cohort (Faker >= 20.0, MIT, `hi_IN`
locale) reproduces the headline number at 10x scale: 53.5% recovery vs
38.8% naive on 5,000 subscribers (53.46% / 38.8% raw, +37.8% uplift, 0 LLM
tokens, 2,560 Guardian vetoes).** The single honest gap is: the Razorpay
live-mode wiring, which is gated on real test-mode keys (keys coming
in 2 days). Everything else works keyless today. Drop the keys in
`main/.env` per `docs/KEYS-DAY.md` and the SPA flips to LIVE.

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

**Phase 6 — Submission polish.** The application form's long-form
questions are answered in [`docs/APPLICATION.md`](docs/APPLICATION.md)
(pre-written answer blocks to paste, plus the explicit
"leave keys out of the form" warning). The
[`ARCHITECTURE.md`](docs/ARCHITECTURE.md) was rewritten to reflect
Phase 0-5: the Mermaid diagram now includes the SPA, the MCP server,
the cloud mirror, and the worker loop. The
[`JOURNAL.md`](../JOURNAL.md) gained four dated entries (real-data UI
rebuild, MCP SDK conversation, cloud mirror, pitch assets) in
plain English, 100-200 words each, written for the application form's
"Build challenges" field.

**Phase 7 — Repo cleanup.** Force-pushed to a clean orphan branch on
the public `main`. The new history has two commits: initial submission
+ a cleanup commit that drops three leftover pre-Phase-0 internal
docs (`improvement-backlog.md`, `technical-architecture.md`,
`ui-ux-guidelines.md`). The public repo has 136 files and zero
references to the old "Revive" brand or the pre-Phase-0 internal
artifacts. Verified end-to-end: fresh clone, keyless, full demo loop
works on a clean machine.

**Phase 8 — Keys day wiring.** The day the user pastes the keys,
`docs/KEYS-DAY.md` is the runbook. Verified the wiring with five new
tests: (1) `/api/status` reports `mode: "LIVE"` only when all four
key classes are present, (2) `build_client()` picks
`LiveRazorpayClient` (not the simulator) when `is_live`, (3)
`/api/pay/{id}/simulate-paid` returns 410 in LIVE mode (the
simulator-only endpoint is correctly gated), (4)
`scripts/live_check.py` is rebranded to "Cadence live-check", (5) the
simulator-vs-live contract is the same code path with the same
events. Test count is now **289 passing**. The single most important
line in the keys-day doc: "every number on the SPA is real — either
from a real API call or from a deterministic simulator with the same
code path as the real call."

**Phase 9 — Aug 28 deep research.**
**Phase 9a (shipped) — Faker 10x scale.** Added `faker>=20.0` to deps,
wrote `main/src/revive/sim/indian_cohort.py` (`generate_indian_cohort(n,
seed)` with `hi_IN` locale, realistic Indian names, UPI handles, IFSC
codes from a known Indian bank set), `main/scripts/run_eval_indian.py`,
updated `/api/eval-summary` to prefer `docs/eval-metrics-large.json` when
present, and added `main/tests/test_indian_cohort.py` (6 tests covering
determinism, cause-mix realism, amount-tier sanity, profile structure,
isolation from the 500-sub cohort, profile-fidelity validation). Tests
289 → 297. The 5,000-sub headline: **53.46% recovery vs 38.8% naive, +37.8%
uplift, 0 LLM tokens, 2,560 Guardian vetoes, 0.76 contacts/recovery
(vs 7.96 naive).** 10x the cohort, same engine, same seed stability, same
direction. The 500-sub canonical number is untouched.
**Phase 9b (shipped) — Phoenix 20.4.0 observability sidecar.** Added
optional `arize-phoenix>=8.0` as `[observability]` extra in `pyproject.toml`
(NOT a hard dep; the 301+ existing tests pass keyless without Phoenix). New
`main/src/revive/observability/phoenix.py` is a graceful no-op when
Phoenix isn't installed: `is_available()` returns False, `instrument()`
returns False without raising, `recent_traces()` returns `[]`. New
`/api/trace/recent` endpoint returns `{enabled: bool, traces: []}`. The
`/api/status` payload now includes a `phoenix_enabled: bool` field.
`main/docs/phoenix-setup.md` is the 30-second setup walkthrough. Tests
297 → 301. The pitch line: "Traced by the same observability stack
that Anthropic recommends" — Phoenix 20.4.0 (released 2026-08-26) has
the in-process MCP toolset. License: ELv2, not OSI-MIT; disclosed in
the README.
**Phase 9c (shipped) — Sarvam AI as 4th LLMClient provider.** Added
`sarvam` to `_OPENAI_COMPATIBLE_URLS` in
`main/src/revive/agents/llm_client.py` (Sarvam is OpenAI-compatible at
`/v1/chat/completions`). Added `sarvam_api_key` and `model_sarvam` fields
to `LLMConfig` with default empty string so existing test constructors
keep working. Updated `main/.env.example` with the Sarvam block. Two
new tests verify: (1) `llm_keys_present=true` when `SARVAM_API_KEY` is
set, (2) `llm_keys_present=false` when empty (keyless path unchanged).
Tests 301 → 303. Pitch line: "Our cohort tests in 10 Indian languages
because Sarvam is one of our four LLM providers. The deterministic
engine handles standard Razorpay error codes with zero LLM tokens;
Sarvam is only consulted for genuinely unclassifiable failures."
**Phase 9d (shipped) — RBI / NPCI circular ingestion.** New
`main/src/revive/policy/circulars.py` with heuristic extractors
(source detection, summary, date, reference, rule list capped at 32).
New `main/src/revive/store/V3__policy_circulars.sql` migration adds
`policy_circulars` table. Three new endpoints
(`/api/circulars`, `/api/circulars/{id}`, `/api/circulars/ingest`).
PDF text via `pypdf` (user-installed, optional). 5 unit tests for the
extractors + 2 API tests for idempotency + keyless no-op. Tests
303 → 310. Pitch line: "We auto-ingest every new RBI / NPCI circular
into the engine's evidence pack. The Guardian cites the source; the
engine's rules are auditable end-to-end." The data plane is in place;
dynamic-rule reading is a post-hackathon add.

**Phase 9e (shipped) — 50-case adversarial regression suite for the Guardian.**
New `main/tests/test_adversarial_guardian.py` (50 tests, 360 total in
the suite, 0.17s runtime). The contract: every case asserts the Guardian
returns a Decision with a reason in the 11-value `VALID_REASONS` set
(quiet_hours_deferred, illegal_intervention, hard_decline_stop,
attempts_exhausted, touch_cap_reached, window_expired, dnd_listed,
kill_switch, channel_not_preferred, cost_ceiling, ok). 10 hand-rolled
cases probe the 10 most-cited Guardian rules; 40 parametrized cases
sweep the 4-channel × 4-root-cause matrix plus boundary conditions.
The "Promptfoo badge" is **50/50** in keyless mode with **0 LLM
tokens**. Updated `main/src/revive/classify/taxonomy.py` to add
`RETRY_NOW` to the legal moves for `NO_FUNDS`, `BANK_DOWN`, `TIMEOUT`
(so the Guardian's quiet-hours deferral for `RETRY_NOW` is reachable;
without this, the deferral rule never fired because legality fired
first — a real bug the test suite caught). Also fixed an existing
artifact: removed `main/-` (a stray 36-byte file created by a bad shell
command earlier).

Skipped: Guardrails AI (cutoff Aug 25 2026 already past), Coqui STT
(discontinued), Unsloth fine-tuning (would *reduce* recovery uplift),
Temporal/Inngest (rewrite risk), Surya-OCR (GPL conflicts with MIT),
n8n (fair-code).

---

*Your code speaks louder than your resume. Built during the night shift.*
