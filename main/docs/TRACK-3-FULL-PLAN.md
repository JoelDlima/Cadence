# Cadence — Track 3 Coverage Plan, 28 Aug 2026

> **Reality check (post audit):** Most of the Track 3 example
> directions are *partially* covered by the existing engine. The
> Promise-to-Pay tracker is **already shipped** (in
> `revive.agents.ptp_parser.py`, used by
> `dispatcher.handle_customer_reply`). The Adaptive Recovery
> Brain is shipped (Phase A). The Indic-language nudge is shipped
> (Phase B). The Bar (measured money, audit chain, 50-case
> matrix) is shipped. The user said: "if 3 features can be
> perfected end to end its considered ideally good." We have 3.
>
> **The remaining Track 3 directions (B2B receivables, checkout
> drop-off, voice TTS, mandate sequencer) are aspirational.**
> The user explicitly said: "adding a lot will spoil the entire
> project. but adding just few proper optimized working features
> is good." We will not add more.

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

## Audit table (28 Aug 2026, end of Day 2)

| # | Direction | Status | What's there | What's missing |
|---|---|---|---|---|
| 1 | Payment degradation → root cause → recovery action | **SHIPPED** | engine.py, bandit.py, guardian.py | "degradation" (partial-success detection) |
| 2 | Checkout drop-off recovery | not built | — | new event type, new chaser |
| 3 | Failed-subscription recovery | **SHIPPED** | engine + bandit + audit + 6-language nudge | nothing |
| 4 | B2B receivables chaser | not built | — | invoice state machine |
| 5 | Mandate retry sequencer | **PARTIAL** | engine handles mandate.* events; Guardian gates; bandit picks | cross-channel sequencer (debit → retry → remitter-bank) |
| 6 | Hinglish voice recovery | **PARTIAL** | Hinglish text in `whatsapp_nudge_text`; 6-language templates | TTS path (Sarvam Bulbul v2) |
| 7 | Promise-to-pay tracker | **SHIPPED** | `agents/ptp_parser.py`, `dispatcher.handle_customer_reply` | nothing |
| 8 | The bar (measured money + audit + 50-case + kill switch) | **SHIPPED** | eval-report.md, hash-chained audit, 50-case matrix, kill switch, touch cap | live "money recovered" SPA widget |

**Shipped: 1, 3, 7, 8 (4 of 8) — these are the 3 + bar.**
**Partial: 5, 6.**
**Not built: 2, 4.**

## What is shipping next (one feature, not six)

The **only** remaining high-value feature is a **live
"money recovered" widget on the SPA Overview tab**. The eval
report already has the 5000-sub number (53.5 % / +37.8 % uplift);
the widget surfaces it on the live dashboard so the judge sees
the number during the demo without opening a terminal.

After that, the rest is docs polish and recording the pitch
video. No new features.

## Skipped (deliberately)

- **Checkout drop-off recovery** (Track 3 #2). The user said
  "few proper optimized working features is good." The engine
  doesn't carry a separate `checkout_abandoned` event type. We
  would have to add a new event, a new chaser, a new SPA tab,
  a new SQL migration, and at least 4 new tests. That's a
  one-day feature, but it dilutes the pitch. The judge will
  look at the 3 perfect ones; checkout drop-off is partial
  coverage and the user is OK with that.
- **B2B receivables chaser** (Track 3 #4). Same reason. The
  engine has an FSM, but a B2B chaser is a different
  customer type, a different cadence, and a different
  escalation chain. Out of scope for the 5-day window.
- **Voice TTS** (Track 3 #6). The Hinglish *text* is shipped.
  TTS via Sarvam Bulbul v2 would add a real Indian-language
  audio path but is a half-day feature. The user said
  "few proper optimized working features is good."
- **Cross-channel mandate sequencer** (Track 3 #5). The
  engine handles `mandate.revoke` and `mandate.paused`. The
  sequencer (debit → retry → remitter-bank) is partial
  coverage through the bandit + Guardian + retry path.

## Why this is the right call

The Track 3 example directions are *examples*, not
*requirements*. The Razorpay site lists 7 directions and
then says: "**The bar:** Don't just identify the problem. Show
measured money recovered across a batch, with compliant
escalation, stopping rules, and an audit trail."

The bar is what the judge scores. We have the bar:
- **Measured money recovered** — 53.5 % on 5000 Indian subs.
- **Compliant escalation** — 8 Guardian rules, 50-case matrix.
- **Stopping rules** — kill switch, touch cap, hard-decline.
- **Audit trail** — hash-chained SQLite, MCP tools, verify
  endpoint.

We have the 3 features the user asked for. We have the bar.
The remaining directions are not the bar; they are flavor.

## What ships next

1. **Live money-recovered widget on the SPA Overview tab** —
   shows the 5000-sub batch number live. Polls `/api/metrics`
   (already exists) and a new `/api/eval/summary` endpoint
   that returns the eval-report headline. ~50 lines of
   React, 1 new API endpoint, 1 new test.
2. **README + PITCH-VIDEO + ARCHITECTURE + JOURNAL polish** —
   all updated to the current truth. Already done for the
   first three; the eval-summary endpoint and the widget
   close the loop.
3. **5-min pitch video** — out of scope for the AI; the user
   records on their machine.

## Risk register

- **The widget's `eval/summary` endpoint must not require the
  Faker dependency at import time.** The eval script lives in
  `scripts/run_eval_indian.py`; the summary endpoint should
  read a cached JSON or call into a small helper that
  doesn't pull in the simulator. Mitigation: the eval-report
  numbers are already cached in
  `main/docs/eval-metrics.json`; the endpoint reads that
  file.
- **The widget must be safe in keyless mode.** It should
  return the cached numbers (deterministic) and never call
  Razorpay. The cached JSON gives us this for free.
