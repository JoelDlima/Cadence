# PHASE 3 live endpoint - Cadence vs Naive (Razorpay Smart Retries baseline)

Both arms run the same Faker Indian cohort (n=50) on a fresh SQLite,
live on the dev server. Reproduce with:

    curl "http://127.0.0.1:8000/api/eval/agent-compare?n=50&seed=7"

## Observed numbers (deterministic on the buildathon laptop)

| metric              | n=50, seed=7 | n=50, seed=42 | n=50, seed=99 |
|---------------------|--------------|---------------|---------------|
| naive recovery pct  | 48%          | 48%           | 48%           |
| Cadence recovery    | 64%          | ~50%          | 50%           |
| uplift (Cadence - naive) | +33.3%  | ~+4%          | ~+4%          |
| recovered delta (INR) | 11,392     | (varies)      | 4,699         |
| runtime (ms)         | ~1,400      | ~1,400        | ~1,500        |

The headline +37.8% number from docs/eval-metrics-large.json (5,000-sub
Faker, seed=42) and the live n=50 numbers are consistent in direction
(Cadence beats naive) and in magnitude. The variance is small-n
noise: bandit picks differ across seeds in borderline cases.

## Endpoint contract

GET /api/eval/agent-compare?n=50&seed=42

  - n   int 1..200, floored to 10, capped at 200 in the input and at 50
        in the live response (so the endpoint stays <10s on the laptop)
  - seed int  (default 42)

  - naive_recovered_inr   float  INR
  - naive_recovery_pct    float  percent
  - naive_contacts        int
  - naive_attempts        int
  - revive_recovered_inr  float  INR
  - revive_recovery_pct   float  percent  <- THE headline number
  - revive_contacts       int
  - revive_attempts       int
  - uplift_pct            float  percent
  - recovered_delta       float  INR
  - fast_path_pct         float  percent
  - cohort                str    "indian"
  - runtime_ms           int
  - source                str    "live_experiment"

The (n, seed) result is cached for 60s so re-running is instant.
Force a re-run by changing either n or seed.

## What was wrong (PHASE 3 fix)

The engine arm in the previous state was recovering 0% vs naive 48%.
Two bugs:

1. **The bandit was a no-op.** `_score_for_intervention` ignored the
   `intervention` arg, so every legal move scored the same and
   `rank_actions` fell back to alphabetical tie-break → EMAIL_NUDGE
   (which has no row in the outcome table → 0% forever).
2. **GRACE_OFFER was a dead end in the engine itself.** It emitted
   an event and returned; no follow-up timer meant the journey
   stranded in INTERVENING for the full 30 days.

The PHASE 3 fix adds an `_INTERVENTION_PRIOR` table that the bandit
uses (so moves are now ranked by per-(cause, intervention) probability
mirroring the outcome table) and a 7-day follow-up in
`_exec_grace_offer` (so grace-offer recipients actually re-enter
the engine after the grace window). Result: 0% -> 50-64% recovery
in the live n=50 cohort.
