# Revive Evaluation Report

Date: 2026-08-26 · Cohort: 500 synthetic subscribers · Seed: 42 · Arms: naive vs revive

## Methodology

- Identical seeded cohort fed to both arms; identical calibrated outcome simulator
  (docs/research-verification-report.md section 6) so the comparison is apples-to-apples.
- Naive arm: one blind retry +24h (p=.25 flat) then emails d1/d3/d5 (p=.06 each),
  ignoring the failure cause entirely.
- Revive arm: real machinery (rules classifier -> Policy Guardian -> durable timers ->
  executors) on SQLite with a FakeClock; deterministic fast path only, zero LLM calls.
- Recovery odds come from the calibrated P(cause, category, attempt) table; link offers
  and reply waits resolve through the same table; every draw is seed-stable.

## Results

| Arm | Recovered | INR recovered | Recovery % | INR per 100 failures | Contacts | Contacts/recovery | Vetoes |
|---|---|---|---|---|---|---|---|
| naive | 189 | 113311.00 | 37.8% | 22662.2 | 1554 | 8.22 | 0 |
| revive | 272 | 166228.00 | 54.4% | 33245.6 | 175 | 0.64 | 228 |

Relative recovery-rate uplift (revive vs naive): **+43.9%**.

**Zero policy violations**: every executed action passed the Guardian pre-action veto layer
(228 vetoes fired at caps/windows/hard-decline stops; 0 illegal actions executed).
Journeys resolved with zero LLM requests: 100%.

## Honest simulation notes

Debits ride simulated NPCI rails: no public merchant API can re-fire an Autopay debit (see
executors/razorpay_client.py), so mandate retries are simulated and Payment Links are the live
instrument. SWITCH_METHOD executions currently return channel_not_wired in the dispatcher, so
BAD_VPA / EXPIRED_INSTRUMENT subscribers stay untreated - a known gap, deliberately not papered
over. Link/nudge conversions are draws from the shared calibrated table, not real payer behavior.
Same seed reproduces this report byte-for-byte.

Artifacts: `docs\eval-report.md`, `docs\eval-metrics.json`.
