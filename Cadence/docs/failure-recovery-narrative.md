# Failure-recovery narrative

Cadence is designed to treat recovery evidence as a product feature. These are the concrete reliability defects found during platform stress testing and reliability hardening, how they were corrected, and the regression proof retained in the repository.

## 1. Duplicate webhook proof was not a replay

**Failure mode.** The early Test Lab “duplicate” drill generated two similar failure payloads. That demonstrates concurrency, but not Razorpay’s actual retry behaviour: a provider replay delivers the *same signed raw event*.

**Fix.** `POST /api/test/inject` now accepts `delivery_count`, reuses the exact raw payload and HMAC signature for each delivery, and returns each delivery status plus the opened journey ID. The UI requires `accepted` followed by `duplicate` before it reports PASS.

**Regression evidence.** `tests/test_api.py::test_test_inject_replay_reports_duplicate_and_one_journey` checks both delivery statuses and verifies that one journey is opened.

## 2. NO_FUNDS outage drill hid a real anomaly

**Failure mode.** The anomaly query grouped raw gateway error codes even after the recovery engine had classified the root cause. A three-event `NO_FUNDS` burst could open three journeys but fail to surface the expected operational alert.

**Fix.** The detector now groups `COALESCE(root_cause, failure_code)`. Test Lab injects three signed failures, verifies that all three create journeys, then reads the `NO_FUNDS` anomaly and recommendation.

**Regression evidence.** `tests/test_api.py::test_test_inject_burst_reports_no_funds_anomaly` asserts the burst, observed count, and anomaly result.

## 3. Live Recovery bypassed the agent path

**Failure mode.** The Live Recovery route previously wrote failure/link facts directly and forced an intervening journey state. That produced a polished view while bypassing the classifier, contextual bandit, Guardian, and normal dispatcher.

**Fix.** Live Recovery now creates the Payment Link, posts a controlled signed `payment.failed` delivery through shared ingress, and runs the normal worker. The direct-engine fallback exists only for minimal legacy test runtimes that do not have a worker.

**Regression evidence.** `tests/test_p1_lifecycle_routes.py::test_live_failure_runs_classifier_bandit_and_guardian` requires `classification.completed`, `bandit.ranked`, and an approval or veto in the timeline.

## 4. An idle Payment Link was not an actionable recovery signal

**Failure mode.** Cadence had a separate prototype checkout model, but it was not tied to the Payment Link projection used by the dashboard. It could not honestly show whether a Razorpay-created link remained payable.

**Fix.** `POST /api/checkout-idle/scan` reads Cadence’s audit-derived Payment Link projection. Only a `created` link older than `CHECKOUT_IDLE_MINUTES` qualifies. It appends `checkout.idle_detected` once per `plink_id`, classifies `ABANDONED_CHECKOUT`, and passes one bounded channel-message proposal through the existing classifier, bandit, Guardian, dispatcher, and audit chain. It explicitly does not claim Magic Checkout abandonment data.

**Regression evidence.** `tests/test_checkout_idle_payment_links.py` proves the full agent path, idempotent replay, paid/expired skips, and audit-chain verification.

## Guardrails retained

- Razorpay Payment Link status is never claimed as `paid` without a real payment outcome.
- Pre-debit reminders are local, test-safe audit events; they make no bank-balance claim and no Razorpay call.
- The kill switch and quiet-hour controls remain Guardian enforcement points for reactive and preventive messaging.
- Calibrated evaluation is labelled synthetic and remains separate from provider-backed Dashboard totals.
