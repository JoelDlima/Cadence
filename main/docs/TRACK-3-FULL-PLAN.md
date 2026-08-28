# Cadence — Track 3 Full Implementation Plan (28 Aug 2026)

> **Goal:** 9.5/10 or 10/10. Cover every Track 3 example direction with
> real, tested, demoable code. Update every doc + every commit to
> reflect the truth of the codebase.

## Track 3 example directions (from the Razorpay site)

1. Payment degradation → root cause → recovery action
2. Checkout drop-off recovery
3. Failed-subscription recovery
4. B2B receivables chaser
5. Mandate retry sequencer
6. Hinglish voice recovery
7. Promise-to-pay tracker

**The bar:** measured money recovered across a batch, with compliant
escalation, stopping rules, and an audit trail.

## Current state (28 Aug 2026, post Phase A+B)

| # | Direction | Status | Score |
|---|---|---|---|
| 1 | Payment degradation → root cause → recovery action | partial | 8/10 |
| 2 | Checkout drop-off recovery | missing | 1/10 |
| 3 | Failed-subscription recovery | shipped | 10/10 |
| 4 | B2B receivables chaser | missing | 1/10 |
| 5 | Mandate retry sequencer | partial | 6/10 |
| 6 | Hinglish voice recovery | missing | 4/10 |
| 7 | Promise-to-pay tracker | partial | 5/10 |
| 8 | The bar (measured batch + audit + escalation + stop) | partial | 8/10 |

**Average: 5.4/10 → target 9.5/10.**

## Plan: 6 features to ship in 6 days, in dependency order

### Feature A — Promise-to-Pay tracker (Day 1)

A customer reply to a nudge may include a *promise* ("I will pay on
the 5th of next month"). The current `_enqueue_reply_wait` waits
generically; it doesn't capture the promise.

**Ship:**
- `revive/policy/promise_parser.py` — regex-based extractor for
  "I will pay on {date}", "next month", "5 tarikh", etc. Returns a
  `(iso_date, amount_minor, confidence)` tuple. Deterministic,
  no LLM.
- `revive/journey/engine.py` — when the customer-reply-wait task
  resolves, run the promise through the parser. If a promise is
  found, schedule a single `RETRY_PAYDAY` intervention on the
  promised date and emit a new `E_PROMISE_CAPTURED` event. If no
  promise, fall through to the existing retry path.
- New `E_PROMISE_CAPTURED` event type.
- `/api/promises/recent` endpoint for the SPA.
- "Promise-to-Pay" card on the Journeys view.
- **5 tests** for the parser + 1 engine test for the full flow.

### Feature B — B2B receivables chaser (Day 2)

A different customer type: org, contact, invoice, terms, escalation
to manager.

**Ship:**
- `revive/store/V4__b2b.sql` — `orgs`, `b2b_invoices`, `b2b_contacts`
  tables.
- `revive/policy/b2b_chaser.py` — invoice-state machine (ISSUED →
  DUE_SOON → OVERDUE → IN_DISPUTE → PAID). For OVERDUE invoices, the
  chaser picks the next action: first nudge (T+3), second nudge
  (T+7), escalation to manager (T+14), written notice (T+21). All
  in the same Guardian + bandit framework as the consumer flow.
- `revive/api/app.py` — `POST /api/b2b/invoice/overdue` to
  trigger a chaser flow.
- New CLI script `scripts/seed_b2b.py` that creates 50 sample
  invoices (10 orgs, 5 invoices each) for the demo.
- SPA: new "B2B Receivables" tab with overdue-by-age and chase
  history.
- **8 tests** for the chaser state machine + 2 API tests.

### Feature C — Hinglish voice recovery (Day 3)

A TTS path that turns a Hinglish nudge into a 15-second voice note
for WhatsApp / voice call.

**Ship:**
- `revive/policy/voice_tts.py` — wraps Sarvam TTS if configured;
  falls back to a deterministic off-line stub that returns a
  base64-encoded silent WAV (so the demo can play *something* in
  keyless mode). The stub is 1 KB; the real path uses Sarvam
  Bulbul v2 (already an LLM provider choice).
- `revive/executors/channels.py` — `MockWhatsApp.send` accepts an
  optional `voice_payload_b64` field. `VoiceChannel` is a new
  transport that combines text + TTS.
- `/api/voice/preview?language=hi&amount_minor=49900` returns
  the text + a base64 WAV stub.
- SPA: a "Voice" toggle on the Indic Nudge preview card that swaps
  text for a play button.
- **3 tests** for the TTS stub + 1 API test.

### Feature D — Checkout drop-off recovery (Day 4)

A customer who starts a checkout but doesn't complete it. Different
from subscription failure: the customer *might* come back on their
own; the chaser is a soft reminder.

**Ship:**
- `revive/policy/checkout_recovery.py` — tracks `checkout_started`,
  `checkout_abandoned`, `checkout_recovered` events. For an
  abandoned checkout, the chaser waits 30 minutes, then sends a
  one-line nudge ("Your cart is waiting, pay in 1 tap"), then
  waits 24 hours, then a second nudge with a 5% discount offer,
  then closes.
- `revive/store/V5__checkout.sql` — `checkout_sessions` table.
- `revive/api/app.py` — `POST /api/checkout/abandon` to simulate
  a drop-off; `POST /api/checkout/recover` to mark it recovered.
- CLI script `scripts/seed_checkout.py` for 100 sessions.
- SPA: "Checkout Recovery" tab with funnel + dropoff rate.
- **4 tests** for the funnel logic + 2 API tests.

### Feature E — Mandate retry sequencer (Day 5)

The current engine handles `mandate.revoke` and `mandate.paused`.
It does NOT intelligently sequence retries across (debit, retry,
remitter-bank).

**Ship:**
- `revive/policy/mandate_sequencer.py` — given a failed mandate,
  compute the optimal next step across:
  - Same-day retry (if cause ≠ BANK_DOWN)
  - 24h retry (if BANK_DOWN, account cooling)
  - Remitter-bank outreach (if 3+ BANK_DOWN in 7 days)
  - Customer switch-method (if mandate paused > 14 days)
- `revive/journey/engine.py` — `handle_mandate_failed()` calls
  the sequencer.
- New `E_MANDATE_SEQUENCED` event.
- `revive/api/app.py` — `POST /api/mandate/failed` to trigger.
- **3 tests** for the sequencer + 1 engine test.

### Feature F — The bar (Day 6)

The user said: "Show measured money recovered across a batch, with
compliant escalation, stopping rules, and an audit trail." The
bar is the **demo page**.

**Ship:**
- New SPA tab "The Bar" that shows:
  - The 5000-sub batch: total recovered, % uplift, total attempted
  - The Guardian's 50-case adversarial matrix (10 × 4 × 4)
  - The audit chain verification widget
  - A live money-recovered counter (from the most recent batch run)
- New `/api/bar/batch` endpoint that runs a 500-sub batch live
  (using the same simulator as `sim/experiment.py`) and returns
  the recovered counter.
- `docs/eval-report.md` updated with the live batch numbers.
- **2 API tests** + a SPA smoke test.

## Docs to update (Day 6, end of day)

- `main/README.md` — phase history block updated with Features A–F.
- `main/JOURNAL.md` — append a "Day 6: shipping the bar" entry.
- `main/docs/ARCHITECTURE.md` — update the request lifecycle
  diagram to show promise-to-pay, B2B, voice, checkout, mandate
  sequencer.
- `main/docs/PITCH-VIDEO.md` — update the shot list to demo each
  new feature (5 new 30-second shots).
- `main/docs/eval-report.md` — add the live batch numbers.
- `IMPLEMENTATION_STATE.md` — full snapshot at the end of Day 6.
- `main/frontend/src/views/BarView.tsx` — new view for the bar.

## Total: 6 days, 6 features, ~40 new tests, 372 → 412 tests,
+~5K lines of code.

## Risk register

- **React/TS bugs.** The biggest risk. Mitigation: keep new
  views under 200 lines; copy from a clean template; build after
  every view; do not add tabs that touch the AppShell more than
  once per day.
- **Schema migrations.** Phase 9d and 9e already shipped 2.
  Feature B, D add 2 more. Mitigation: idempotent migrations;
  rollback tested.
- **Demo length.** 6 features in 5 minutes is too many.
  Mitigation: PITCH-VIDEO.md updated to 7 minutes; the pitch
  focuses on 3 features (subscription, B2B, voice) and demos
  the bar at the end.

## Daily check-in pattern

- Each day ends with: `pytest tests` ≥ N passing, `npm run build`
  clean, force-push to `submission-clean:main`, `git log --oneline`
  shows the day's commits.
- IMPLEMENTATION_STATE.md is updated at the end of each day.
