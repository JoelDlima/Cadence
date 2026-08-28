# Cadence — Track 3 Full Implementation Plan (rev 2, 28 Aug 2026)

> **Audit (after Razorpay site fetch, 28 Aug 2026):** Track 3 lists
> 7 example directions. We have **3 of 7 fully shipped** (A
> Adaptive Recovery Brain, B Indic-language nudge, PTP
> tracker) plus the bar (measured money). The 4 example
> directions we are **not shipping** are the user's lost
> points.
>
> The user is right: we need all 7. Stop rationalizing.

## Track 3 example directions (verbatim from the Buildathon site)

1. Payment degradation → root cause → recovery action **— SHIPPED (Phase A)**
2. Checkout drop-off recovery **— NOT BUILT**
3. Failed-subscription recovery **— SHIPPED (Phase 0–8)**
4. B2B receivables chaser **— NOT BUILT**
5. Mandate retry sequencer **— PARTIAL (engine handles mandate events; cross-channel sequencer missing)**
6. Hinglish voice recovery **— PARTIAL (Hinglish text shipped; TTS path missing)**
7. Promise-to-pay tracker **— SHIPPED (revive.agents.ptp_parser)**

**Bar (verbatim):** "Don't just identify the problem. Show measured
money recovered across a batch, with compliant escalation, stopping
rules, and an audit trail."

**Cross-cutting bar (Track 1's bar, applies to all tracks):**
"Every money action explainable, bounded and gated. Show the audit
trail and one failure handled gracefully."

## Plan: ship the 4 missing directions in 4 phases, in dependency order

### Phase 1 — Checkout drop-off recovery (Day 1)

A customer who starts a Razorpay checkout but doesn't complete it.
Different from subscription failure: the customer *might* come
back on their own; the chaser is a soft reminder that respects
NPCI quiet hours.

**What Razorpay has for checkout:**
- `client.payment_link.create(...)` — creates a payment link
- `client.payment_link.notify_by(linkId, medium)` — sends SMS/email
- Webhook: `payment_link.paid`, `payment_link.cancelled`,
  `payment_link.expired`

**Ship:**
- `main/src/revive/store/V4__checkout.sql` —
  `checkout_sessions(id, customer_id, amount_minor, currency,
   started_at, abandoned_at, status, last_nudge_at, recovered_at,
   created_payment_link_id)`.
- `main/src/revive/checkout/recovery.py` — pure-Python state
  machine: `OPEN → ABANDONED → NUDGED_T1 → NUDGED_T2 → RECOVERED |
   EXPIRED`. The chaser decides the next nudge based on time-since
   abandonment and touch cap. **Reuses the same Guardian +
   Adaptive Recovery Brain** as the subscription path — no new
   rules needed.
- `main/src/revive/checkout/api.py` — `POST /api/checkout/abandon`
  (simulate a drop-off), `POST /api/checkout/recover` (mark
  recovered), `GET /api/checkout/sessions?limit=50`.
- `main/src/revive/checkout/seed.py` — 100 sample abandoned
  sessions.
- SPA: a "Checkout Recovery" tab with funnel + dropoff-by-age.
- 6 tests (3 for the state machine, 2 for API, 1 for seed
  determinism).

### Phase 2 — B2B receivables chaser (Day 2)

Razorpay has full invoice API: `client.invoice.create / fetch /
all / issue / cancel / notify_by`. The chaser hooks into the
invoice state machine.

**Ship:**
- `main/src/revive/store/V5__b2b.sql` —
  `b2b_invoices(id, customer_id, amount_minor, currency,
   due_date, status, issued_at, paid_at, last_chase_at, chases_sent)`.
- `main/src/revive/b2b/chaser.py` — invoice state machine
  (`ISSUED → DUE_SOON → OVERDUE → IN_DISPUTE → PAID`). For
  OVERDUE invoices, the chaser picks the next action:
  - T+3 (3 days past due): friendly nudge (Hinglish/English)
  - T+7: firmer nudge with UPI deep-link
  - T+14: escalation to manager (different recipient)
  - T+21: written notice (legal tone)
  - T+45: write-off (stops further chases)
- `main/src/revive/b2b/api.py` —
  `POST /api/b2b/invoice/create` (seed),
  `GET /api/b2b/invoices?status=overdue&limit=50`,
  `POST /api/b2b/invoice/{id}/chase` (manual trigger).
- `main/src/revive/b2b/seed.py` — 50 sample B2B invoices (10
  orgs × 5 invoices each, varying due states).
- SPA: a "B2B Receivables" tab with overdue-by-age and chase
  history.
- 8 tests (3 for the chaser ladder, 2 for the dispute path,
  2 for API, 1 for the write-off stop).

### Phase 3 — Mandate retry sequencer (Day 3)

A failed UPI AutoPay mandate. The current engine handles
`mandate.revoke` and `mandate.paused` as a single cause. The
sequencer adds cross-channel logic: given a failed mandate,
compute the optimal next step across same-day retry, 24h retry
(bank cooling), remitter-bank outreach (3+ BANK_DOWN in 7d),
and customer switch-method (mandate paused > 14d).

**Ship:**
- `main/src/revive/mandate/sequencer.py` — pure function
  `next_step(mandate_state, recent_failures, ...) -> (action,
  schedule_at, reason)`. Uses the bandit and Guardian the same
  way the engine does. The output action is one of: `RETRY_NOW`,
  `RETRY_24H`, `REMITTER_OUTREACH`, `SWITCH_METHOD`,
  `STOP_AND_HUMAN_REVIEW`.
- Engine hook: `engine.handle_mandate_failed()` now calls the
  sequencer before the bandit.
- New event `E_MANDATE_SEQUENCED` for the audit chain.
- `main/src/revive/mandate/api.py` —
  `POST /api/mandate/failed` (simulate a mandate failure),
  `GET /api/mandate/sequenced?limit=25`.
- SPA: a small "Mandate Sequencer" card on the existing
  Recovery Brain tab (no new nav item).
- 5 tests (3 for the sequencer ladder, 1 for engine hook, 1
  for API).

### Phase 4 — Hinglish voice recovery (Day 4)

A TTS path that turns a Hinglish nudge into a 15-second voice
note for WhatsApp / voice call. The "voice" is the next
evolution of the Indic-language nudge.

**Ship:**
- `main/src/revive/policy/voice_tts.py` — wraps Sarvam Bulbul
  v2 TTS if `SARVAM_API_KEY` is set. Falls back to a
  deterministic off-line stub that returns a 1 KB silent WAV
  (so the demo can play *something* in keyless mode). The
  stub's determinism is proven by a test.
- `main/src/revive/executors/channels.py` — `MockWhatsApp.send`
  accepts an optional `voice_payload_b64` field.
- `main/src/revive/policy/nudge_templates.py` — add a
  `voice_payload_b64: str | None` field to the
  `nudge_for_language` return signature.
- `main/src/revive/api/app.py` — `GET /api/voice/preview` returns
  text + base64 WAV.
- SPA: a "Voice" toggle on the Indic Nudge preview card.
- 4 tests (2 for the TTS stub, 1 for the API, 1 for the
  channel path).

## Total: 4 days, 4 features, ~25 new tests, 372 → ~400 tests,
+~2,500 lines of code.

## Daily check-in pattern

- Each phase ends with: `pytest tests` ≥ N passing, `npm run
  build` clean, force-push to `submission-clean:main`, `git
  log --oneline` shows the day's commits.
- All .md docs updated to reflect the new features before push.

## Risk register

- **React/TS bugs.** Already saw 2 build failures from string
  escaping. Mitigation: keep new views under 200 lines; copy
  from a clean template; build after every view.
- **Schema migrations.** Two new SQL files. Mitigation:
  idempotent migrations; rollback tested.
- **Sarvam TTS without API key.** The stub WAV is 1 KB silent.
  Mitigation: the stub is deterministic and the tests prove
  it; the real path is a one-line change in `voice_tts.py` when
  the key arrives.

## What I will NOT skip (judge's perspective)

All 7 example directions. The user is right: a partial
implementation signals "we didn't read the brief." The 5,000-sub
Indian cohort headline is the bar; the 7 directions are the
checklist the judge uses to mark off whether we hit each one.
