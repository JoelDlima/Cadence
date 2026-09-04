# Cadence revamp implementation plan

**Status:** implemented and awaiting final validation/publish
**Branch target:** `revamp` (created and pushed during the final Git phase)
**Scope:** turn Cadence from a strong controlled failed-payment demo into a defensible AI Revenue Recovery platform with four fully working product capabilities: strict mandate retry sequencing, pre-debit prevention, checkout-idle recovery, and visible calibrated batch evidence.

## Goals

Cadence must visibly demonstrate:

```text
prevent → detect → diagnose → decide → execute → measure → audit
```

The revamp must not make unsupported claims. Every UI item must state whether it is:

- a real Razorpay Test Mode operation;
- a controlled signed event through Cadence's normal webhook path;
- a deterministic local synthetic portfolio/evaluation result; or
- disabled pending third-party credentials.

## Non-goals

- Do not claim bank-balance access without explicit consented account-data integration.
- Do not claim a Razorpay Payment Link is paid unless a real Razorpay checkout made it paid.
- Do not add a production WhatsApp sender without Twilio credentials, Sandbox opt-in, and Guardian consent controls.
- Do not add B2B receivables in this revamp. It needs a separate invoice/collections domain model.
- Do not expose test-only lifecycle outcome routes in the main product UI.

## Phase 0 — proof baseline and visible defects

### Deliverables

1. Keep only the five visible Test Lab drills:
   - duplicate webhook;
   - NO_FUNDS burst/anomaly;
   - out-of-order delivery;
   - kill switch;
   - real Razorpay Payment Link cancellation.
2. Fix the Live Recovery voice control so it is visible whenever a generated message exists, and it clearly says whether it is provider-generated audio or a stub.
3. Ensure stale customer-hint controls are removed when the autonomous test-only drill is hidden.
4. Preserve the explicit Created-versus-Paid Razorpay boundary.

### Acceptance checks

- The Test Lab shows `5 drills`, not nine.
- Duplicate result reads accepted then duplicate.
- NO_FUNDS result reads 3/3 journeys and WARN anomaly.
- Voice control appears after an agent message is available.
- `npm run build` passes.

## Phase 1 — hard mandate retry sequence

### Product behaviour

A mandate gets exactly one initial execution plus up to three retries:

| Sequence | Meaning | Result |
| ---: | --- | --- |
| 1 | initial mandate execution | allowed if other Guardian rules pass |
| 2 | retry 1 of 3 | allowed if other Guardian rules pass |
| 3 | retry 2 of 3 | allowed if other Guardian rules pass |
| 4 | retry 3 of 3 | allowed if other Guardian rules pass |
| 5+ | retry cap exceeded | hard Guardian veto |

### Implementation

- Guardian reason: `mandate_retry_limit_exhausted`.
- Preserve UPI cooling, quiet hours, notice, amount and kill-switch controls.
- Add audit payload fields to `intervention.approved`:
  - `mandate_execution_sequence`;
  - `mandate_retry_number`;
  - `mandate_retry_limit`.
- Show those values in `/api/journey/{id}/reasoning` and the Dashboard drawer.
- Treat the cap as a hard veto, not a preference score or frequency-decay hint.

### Files expected

- `src/cadence/policy/guardian.py`
- `src/cadence/journey/engine.py`
- `src/cadence/api/app.py`
- `frontend/src/views/DashboardView.tsx`
- `tests/test_guardian.py`
- relevant engine/reasoning tests

### Acceptance checks

- Sequence 4 can be approved.
- Sequence 5 is vetoed with `mandate_retry_limit_exhausted`.
- The audit trail contains the sequence fields.
- Dashboard reasoning exposes `retry N of 3`.

## Phase 2 — prevention: scheduled pre-debit nudge

### Product behaviour

Cadence creates a prevention workflow before a scheduled debit. The nudge does not claim to know the bank balance. It says the debit is upcoming and asks the customer to ensure sufficient balance or update their payment method.

```text
scheduled execution
→ configurable lead window (default 24h)
→ prevention.scheduled
→ Guardian checks contact/mandate/quiet-hour controls
→ prevention.approved or prevention.vetoed
→ LLM-written Hinglish pre-debit message
→ email/voice execution when configured
→ prevention.sent
→ later payment outcome linked to mandate sequence
```

### Distinct event taxonomy

- `prevention.scheduled`
- `prevention.approved`
- `prevention.vetoed`
- `prevention.sent`
- root cause/context: `PRE_DEBIT_LOW_BALANCE_RISK`

### API and frontend proof

- A test-safe API creates a scheduled mandate and runs the preventive workflow.
- Live Recovery or a dedicated Dashboard card displays:
  - scheduled debit time;
  - lead window;
  - Guardian result;
  - generated message;
  - delivery status;
  - audit event references.
- The action is labelled **Preventive reminder**, not recovery after failure.

### Acceptance checks

- A valid schedule produces prevention events and generated message.
- Quiet hours, DND, kill switch, preference and invalid mandate block it.
- It does not create a payment failure or pretend the customer has low balance.

## Phase 3 — checkout-idle recovery

### Product behaviour

An existing Razorpay Payment Link that remains `created` past a configurable idle threshold becomes a Cadence checkout-risk journey.

```text
Payment Link created
→ idle threshold passes
→ checkout.idle_detected
→ root cause ABANDONED_CHECKOUT
→ classifier/bandit/Guardian/dispatcher
→ one bounded reminder containing existing short URL
→ paid/cancelled/expired/ignored outcome
```

### Integrity constraints

- One idle detection per Payment Link reference.
- Never create a checkout-idle journey for paid or cancelled links.
- No message while Guardian blocks contact.
- This is self-managed Payment Link idle detection, not a claim that Razorpay Magic Checkout sent an abandoned-cart event.

### API and frontend proof

- Test Lab or Dashboard has a visible `Detect idle checkout` action against a created link.
- Result displays threshold, detected time, root cause, chosen action, Guardian result, and short URL.
- Dashboard labels the journey root cause `ABANDONED_CHECKOUT`.

### Acceptance checks

- Created link past threshold opens one journey.
- Second check is idempotent.
- Paid/cancelled links are skipped.
- Audit chain verifies.

## Phase 4 — calibrated batch evidence

### Product behaviour

Dashboard visibly distinguishes live evidence from local calibrated evidence.

```text
Live Razorpay Test Mode: actual customer/link/cancel/payment evidence
Calibrated synthetic portfolio: deterministic local batch used for policy measurement
```

### Dashboard card

Display data from `/api/eval/agent-compare`:

- fixed retry baseline recovery rate;
- Cadence policy recovery rate;
- relative and percentage-point lift;
- five seed identifiers;
- subscribers per seed;
- clear label: `Calibrated simulation — not production results`.

### Synthetic portfolio

- Create 50 deterministic local-only rows for demonstration.
- Never call Razorpay, Resend, Supabase or external providers.
- Each row carries `synthetic: true`.
- Keep synthetic portfolio separate from live Payment Link table totals or show a clear filter/badge.

### Acceptance checks

- Dashboard displays the evaluation card without restoring the removed agent-comparison Test Lab UI.
- Seeded data is deterministic and clearly synthetic.
- Live rows remain distinguishable from synthetic rows.

## Phase 5 — documentation and demo runbook

### Required updates

- README: add real-versus-controlled evidence table, phase features, and honest limitations.
- `docs/demo-script.md` and `docs/demo-script.pdf`: explain prevention, mandate sequence, checkout-idle, batch evidence, and the customer/Razorpay/Cadence three-view demonstration.
- `implementation.md`: update the local working guide.
- Add `docs/failure-recovery-narrative.md` with real bugs found, root cause, fix, and regression tests.

### Failure-recovery narrative candidates

1. Duplicate webhook drill initially sent one event rather than a replay; fixed by reusing the identical signed payload and verifying accepted → duplicate.
2. NO_FUNDS burst opened journeys but did not show an anomaly because the detector compared raw error codes rather than classified root cause; fixed by counting `root_cause`.
3. Live Recovery originally bypassed the agent worker; fixed by sending the controlled payload through the shared signed gateway and worker.

## Deferred integrations

### Twilio WhatsApp Sandbox

Implement only after the following variables are supplied:

```text
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_WHATSAPP_FROM
TWILIO_SANDBOX_ENABLED=true
```

Additionally, the recipient must opt in to the Sandbox. Production use requires approved sender/templates and consent/opt-out controls.

### Public Razorpay webhook

For automatic real checkout detection, Cadence needs a public HTTPS callback URL:

```text
https://<public-host>/webhooks/razorpay
```

Configure Razorpay Test Mode events: `payment_link.paid`, `payment.failed`, `payment.captured`, `subscription.pending`, `subscription.halted`.

## Commit strategy

At the end of each completed phase:

1. Run targeted tests and frontend build.
2. Stage only phase files.
3. Commit with one focused message.
4. Push `revamp` with upstream tracking.

Suggested commits:

```text
feat(guardian): enforce auditable mandate retry sequence
feat(prevention): add compliant pre-debit nudge workflow
feat(checkout): recover idle payment links
feat(dashboard): surface calibrated batch evidence
feat(docs): add failure-recovery narrative and revamp demo
```

## Implementation record

Completed in this revamp:

- **Phase 0:** five visible Test Lab drills, corrected duplicate/burst proof, and a visible disabled audio control when no approved message exists.
- **Phase 1:** one initial mandate execution plus three retries; sequence five is a Guardian hard veto and approved events expose sequence metadata.
- **Phase 2:** `predebit.scheduled` / `predebit.notified` prevention workflow, Guardian suppression, API tests, dedicated view, and Test Lab proof card. It is local and makes no Razorpay or bank-balance claim.
- **Phase 3:** audit-projected, created-only Payment Link idle scan with `checkout.idle_detected`, idempotency per `plink_id`, `ABANDONED_CHECKOUT`, one bounded message legal move, and Dashboard proof. It is not Magic Checkout telemetry.
- **Phase 4:** Dashboard-only five-seed × 50 calibrated evidence card. It remains explicitly synthetic and separate from live link totals; no fake provider rows were introduced.
- **Phase 5:** README evidence boundary, revised demo script/PDF, and `docs/failure-recovery-narrative.md`.

## Final validation

```text
pytest -q
npm run build
verify_5_drills.py
manual Live Recovery
manual real Razorpay cancellation
manual customer/Razorpay/Cadence three-view rehearsal
```
