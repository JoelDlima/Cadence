# Improvement Backlog — Differentiation Research (Aug 2026)

Research basis: 2026 dunning/recovery industry feature sets and benchmarks (Recurly,
Chargebee, ProfitWell data cited via DunningCompare 2026; Slicker, RetryKit, Prevenue,
conversational-recovery studies). Purpose: make Revive measurably better than the
dozens of similar buildathon submissions, in USE and FUNCTIONALITY — not cosmetics.

## Benchmark validation of our current eval (important for pitch)

Independent 2026 benchmarks: 70% of involuntary churn is recoverable with a complete
dunning stack (Recurly); 57% achievable with best-practice sequences (Chargebee);
email-only dunning recovers ~30%; conversational channels (WhatsApp/SMS) recover
68-75%; failed payments drain 9-12% of MRR yearly; $0.12 recovered per $1 at risk.
Our numbers sit INSIDE these bands: naive arm 37.8% (matches email-only ~30-40%),
Revive 54.4% (between email-only and full-stack ceiling — credible because our
WhatsApp is mocked and card-updater layer absent). Add line to evidence pack:
"our results are conservative against the 70% full-stack ceiling."

## TIER 1 — build now (high pitch value, days of work)

1. **Self-service recovery page** (`/pay/{journey_id}`): hosted "fix your payment"
   page rendered by our FastAPI — shows amount, cause in plain words, one-tap Razorpay
   checkout / payment link. Every nudge message links to it. Industry consensus: this
   one page fixes the top root causes and is standard in every commercial dunning tool.
   Makes our channels CONVERSIONAL instead of informational. (est. 1 day)
2. **Recovery score** (customer-value weighting): score = f(amount, failure history,
   promise history) → drives intervention intensity and contact-channel order. High
   score gets WhatsApp+email+link; low gets single email. Turns our flat policy into
   risk-based triage — the thing "smart dunning vs basic retries" literature says
   recovers 3x more. (est. 0.5 day)
3. **Bank-outage circuit breaker** (anomaly guard): if failures with the same
   error_code spike across journeys in a window (e.g., bank_technical_error from one
   issuer), pause nudges for that cause, batch retries after recovery. Prevents
   harassing 10,000 customers during one SBI downtime. Very India-relevant, very
   demoable, extends Guardian naturally. (est. 1 day)
4. **Cost-per-recovery budgeter** (Guardian rule): projected recovery cost (contacts
   + tokens) must stay under a fraction of amount at risk; else stop and close. New
   metric line in eval report: cost efficiency vs industry $0.12/$1 benchmark. (est. 0.5 day)
5. **Conversational-channel upgrade path**: cite the 68-75%-vs-30% stat in README/pitch
   to justify WhatsApp priority; wire the mock's scripted replies through the SAME
   self-service page so the flow is end-to-end clickable even in demo. (est. 0.5 day)

## TIER 2 — strong, if time remains

6. **Issuer-aware retry timing**: static table of Indian issuer behaviors (payday
   clusters, known downtime patterns) → per-bank retry windows; upgradeable to learned
   rates. Literature: bank-pattern models compound over time. (1 day)
7. **Save-offer ladder**: before closing unrecovered → grace period → pause → downgrade
   offer (policy-capped). Measure save-rate separately from recovery-rate. (1 day)
8. **Indian calendar awareness**: no nudges on national holidays/festival weeks
   (NPCI holiday list); salary-week weighting already exists — extend to avoid
   Diwali-week contact spam. (0.5 day)
9. **Preference center**: customer replies "whatsapp only mornings" → stored
   preferences honored by Guardian channel selection. (0.5 day)
10. **Console cohort analytics**: recovery rate by cause / amount band / channel —
    three group-bys on existing events, no new infra. (0.5 day)

## TIER 3 — post-buildathon roadmap (documented, not built)

11. Card account-updater / TokenHub integration (network tokens)
12. Product-usage + support signals in the recovery queue (Prevenue pattern)
13. Continuous A/B framework (we have one-shot eval; productize it)
14. Multi-merchant tenancy + auth
15. Webhook replay/backfill admin tool
16. B2B receivables loop via Smart Collect (track brief's overdue-invoices slice)

## Pitch framing against the crowded field

- Most entries: chatbot + retries. Revive: decline-code triage + governed autonomy +
  measured recovery — the exact "smart dunning vs basic retries" 3x-gap the industry
  literature documents, reproduced by a student at test-mode scale.
- Tier-1 items convert our biggest honest gaps (mock WhatsApp, no customer-facing page)
  into the industry's two highest-leverage features (conversational recovery +
  self-service page) — both cited at 68-75% recovery in 2026 sources.
