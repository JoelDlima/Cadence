# Cadence Evaluation Report

Date: 2026-08-28 · Cohorts: 500 + 5,000 synthetic Indian subscribers · Seed: 42 · Arms: naive vs Cadence

## Two cohorts, one story

The 500-sub cohort is the canonical, repeatable baseline. The 5,000-sub
cohort is the **pitch-deck headline** — same seed, same calibrated
simulator, ten times the volume. Both are apples-to-apples with the
naive arm.

## Methodology

- Identical seeded cohort fed to both arms; identical calibrated
  outcome simulator so the comparison is apples-to-apples.
- Naive arm: one blind retry +24h (p=.25 flat) then emails d1/d3/d5
  (p=.06 each), ignoring the failure cause entirely.
- Cadence arm: real machinery (rules classifier → Adaptive Recovery
  Brain → Policy Guardian → durable timers → executors) on SQLite
  with a FakeClock; deterministic fast path only, zero LLM calls.
- Recovery odds come from the calibrated P(cause, category, attempt)
  table; link offers and reply waits resolve through the same table;
  every draw is seed-stable.
- **Adaptive Recovery Brain** (Phase A, Day 2): a deterministic
  contextual bandit in `revive.policy.bandit` scores every legal
  move for the (cause, context) tuple. The chosen top is a legal
  intervention for the cause; the engine emits a `bandit.ranked`
  event with the full ranked list, scores, reason, and feature
  importances.
- **Promise-to-Pay** (already shipped, `revive.agents.ptp_parser`):
  a customer reply like "I'll pay on the 5th" gets parsed
  deterministically (regex, multi-lingual Hinglish + English) and
  the engine schedules a single `RETRY_PAYDAY` intervention on
  the promised date.

## Results

### 500-sub cohort (canonical, baseline)

| Arm | Recovered | INR recovered | Recovery % | INR per 100 failures | Contacts | Contacts/recovery | Vetoes |
|---|---|---|---|---|---|---|---|
| naive | 189 | 113,311 | 37.8% | 22,662 | 1,554 | 8.22 | 0 |
| Cadence | 272 | 166,228 | 54.4% | 33,246 | 175 | 0.64 | 228 |

Relative recovery-rate uplift (Cadence vs naive): **+43.9%**.

### 5,000-sub Indian cohort (Phase 9a, pitch-deck headline)

| Arm | Recovered | INR recovered | Recovery % | INR per 100 failures | Contacts | Contacts/recovery | Vetoes |
|---|---|---|---|---|---|---|---|
| naive | 1,940 | 1,154,660 | 38.8% | 23,093 | 15,434 | 7.96 | 0 |
| Cadence | 2,673 | 1,610,927 | 53.46% | 32,219 | 2,043 | 0.76 | 2,560 |

Relative recovery-rate uplift (Cadence vs naive): **+37.8%**.

**Zero policy violations**: every executed action passed the Guardian
pre-action veto layer (2,560 vetoes fired at caps/windows/hard-decline
stops on the 5,000-sub run; 0 illegal actions executed). Journeys
resolved with zero LLM requests: 100%.

## Honest simulation notes

Debits ride simulated NPCI rails: no public merchant API can re-fire
an Autopay debit, so mandate retries are simulated and Payment Links
are the live instrument. SWITCH_METHOD executions currently return
`channel_not_wired` in the dispatcher, so BAD_VPA / EXPIRED_INSTRUMENT
subscribers stay untreated — a known gap, deliberately not papered
over. Link/nudge conversions are draws from the shared calibrated
table, not real payer behavior. Same seed reproduces this report
byte-for-byte.

## What this proves (the bar)

The Track 3 example bar is: "Show measured money recovered across a
batch, with compliant escalation, stopping rules, and an audit trail."

| Bar element | Evidence in Cadence |
|---|---|
| Measured money recovered | ₹1,610,927 across 5,000 Indian subscribers; ₹166,228 across 500 |
| Compliant escalation | 8 Guardian rules; 2,560 vetoes on the 5,000 run; 0 violations |
| Stopping rules | Kill switch, touch cap, hard-decline, quiet hours, RBI 24h pre-debit notice |
| Audit trail | Hash-chained SQLite ledger, MCP server, `/api/audit/verify` endpoint |

**The 5-minute demo can show every one of these on the live SPA.**

Artifacts: `docs/eval-report.md`, `docs/eval-metrics.json` (500-sub),
`docs/eval-metrics-large.json` (5,000-sub).
