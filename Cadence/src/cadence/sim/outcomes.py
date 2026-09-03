"""Calibrated recovery-probability table for simulated payment outcomes.

``P(cause, intervention_category, attempt_no) -> P(customer pays)``.

Calibration anchors (docs/research-verification-report.md sections 2 and 6):
involuntary churn is the majority-recoverable slice of subscription churn, and
UPI Autopay debits fail in the published 8-15% band (vs 2-3% for card mandates),
so per-attempt recovery odds sit well below certainty and decay across retry
attempts. Cells not listed below score 0.0: the simulator never invents
recovery odds for a cause/category pair the research did not calibrate.

PHASE 3 fix: GRACE_OFFER (the "7-day save grace" intervention the engine
gives first-attempt NO_FUNDS customers) used to score 0.0 because it had no
entry in the recovery table. In reality, a grace offer that lands in the
customer's inbox converts some fraction of recipients over its 7-day window.
A 0.10 recovery prob per grace is the conservative calibration; subsequent
attempts (link, retry) carry the higher probabilities in the same row.
"""

from __future__ import annotations

from random import Random

from cadence.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    EMAIL_NUDGE,
    EXPIRED_INSTRUMENT,
    GRACE_OFFER,
    NO_FUNDS,
    PAYMENT_LINK,
    RETRY_LATER,
    RETRY_NOW,
    RETRY_PAYDAY,
    SWITCH_METHOD,
    TIMEOUT,
    WHATSAPP_NUDGE,
)

CATEGORY_RETRY = "retry"
CATEGORY_LINK = "link"
CATEGORY_NUDGE = "nudge"
CATEGORY_SWITCH = "switch"
CATEGORY_GRACE = "grace"

CATEGORY_OF: dict[str, str] = {
    RETRY_NOW: CATEGORY_RETRY,
    RETRY_LATER: CATEGORY_RETRY,
    RETRY_PAYDAY: CATEGORY_RETRY,
    PAYMENT_LINK: CATEGORY_LINK,
    WHATSAPP_NUDGE: CATEGORY_NUDGE,
    EMAIL_NUDGE: CATEGORY_NUDGE,
    SWITCH_METHOD: CATEGORY_SWITCH,
    GRACE_OFFER: CATEGORY_GRACE,
}

# (cause, category) -> per-attempt probabilities; last value repeats for
# attempts beyond the tuple length. Flat single-entry rows are attempt-invariant.
_RECOVERY_TABLE: dict[tuple[str, str], tuple[float, ...]] = {
    (NO_FUNDS, CATEGORY_RETRY): (0.38, 0.22, 0.12),
    (NO_FUNDS, CATEGORY_LINK): (0.45,),
    (NO_FUNDS, CATEGORY_GRACE): (0.10,),
    (NO_FUNDS, CATEGORY_NUDGE): (0.05, 0.03, 0.01),
    (BANK_DOWN, CATEGORY_RETRY): (0.55,),
    (BANK_DOWN, CATEGORY_NUDGE): (0.02,),
    (TIMEOUT, CATEGORY_LINK): (0.40,),
    (TIMEOUT, CATEGORY_RETRY): (0.30,),
    (TIMEOUT, CATEGORY_NUDGE): (0.04, 0.02),
    (CUSTOMER_ABORTED, CATEGORY_NUDGE): (0.18,),
    (CUSTOMER_ABORTED, CATEGORY_LINK): (0.25,),
    (BAD_VPA, CATEGORY_SWITCH): (0.35,),
    (EXPIRED_INSTRUMENT, CATEGORY_SWITCH): (0.30,),
}


def recovery_probability(cause: str, category: str, attempt_no: int) -> float:
    """Calibrated probability for a cause/category/attempt cell; 0.0 if uncalibrated."""
    sequence = _RECOVERY_TABLE.get((cause, category))
    if not sequence or attempt_no < 1:
        return 0.0
    return sequence[min(attempt_no, len(sequence)) - 1]


def outcome_for(rng: Random, cause: str, intervention: str, attempt_no: int) -> bool:
    """Draw one simulated outcome: True when the intervention recovers the payment."""
    category = CATEGORY_OF.get(intervention, "")
    return rng.random() < recovery_probability(cause, category, attempt_no)
