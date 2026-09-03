"""Seeded synthetic failure cohort calibrated to the published failure mix.

Cause weights follow docs/research-verification-report.md section 6 (UPI-band
calibration): NO_FUNDS dominates, hard declines and instrument problems stay
minor. Every known cause maps to a REAL Razorpay-style ``error_code`` string
from ``taxonomy.ERROR_CODE_MAP`` keys so the production classifier sees
realistic payloads; the unknown remainder carries no code at all and is sent
with a deliberately unmapped simulator code.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any

from cadence.classify.taxonomy import (
    BAD_VPA,
    BANK_DOWN,
    CUSTOMER_ABORTED,
    ERROR_CODE_MAP,
    EXPIRED_INSTRUMENT,
    HARD_DECLINE,
    NO_FUNDS,
    TIMEOUT,
    UNKNOWN,
)

SIM_UNKNOWN_CODE = "sim_unknown_9812"

_CAUSE_WEIGHTS: tuple[tuple[str, float], ...] = (
    (NO_FUNDS, 0.45),
    (BANK_DOWN, 0.12),
    (TIMEOUT, 0.10),
    (CUSTOMER_ABORTED, 0.12),
    (HARD_DECLINE, 0.06),
    (BAD_VPA, 0.07),
    (EXPIRED_INSTRUMENT, 0.05),
)
# Remainder of the mix (1 - sum(weights)) becomes unknown-code failures.

_FAILURE_CODES: dict[str, str] = {
    NO_FUNDS: "insufficient_funds",
    BANK_DOWN: "bank_technical_error",
    TIMEOUT: "payment_collect_request_expired",
    CUSTOMER_ABORTED: "payment_cancelled",
    HARD_DECLINE: "card_declined",
    BAD_VPA: "invalid_vpa",
    EXPIRED_INSTRUMENT: "expired_card",
}

_FAILURE_DESCRIPTIONS: dict[str, str] = {
    NO_FUNDS: "insufficient funds to complete the autopay debit",
    BANK_DOWN: "technical error at issuing bank, debit not attempted",
    TIMEOUT: "upi collect request expired before customer approval",
    CUSTOMER_ABORTED: "customer cancelled the payment request",
    HARD_DECLINE: "card declined by issuer with no retry permitted",
    BAD_VPA: "invalid vpa: handle does not exist",
    EXPIRED_INSTRUMENT: "instrument expired at issuer",
}
_UNKNOWN_DESCRIPTION = "issuer rejected the debit without a mapped reason"

# (amount_minor, weight) tiers spanning Rs 199 .. Rs 2,999.
_AMOUNT_TIERS: tuple[tuple[int, int], ...] = (
    (19900, 30),
    (29900, 25),
    (49900, 20),
    (99900, 12),
    (149900, 7),
    (199900, 4),
    (299900, 2),
)


@dataclass(frozen=True)
class SimSubscriber:
    """One synthetic failed-debit record feeding both experiment arms."""

    subscription_id: str
    customer_id: str
    amount_minor: int
    failure_code: str | None  # None => unknown-code remainder of the mix
    error_description: str


def _draw_cause(rng: Random) -> str | None:
    roll = rng.random()
    cumulative = 0.0
    for cause, weight in _CAUSE_WEIGHTS:
        cumulative += weight
        if roll < cumulative:
            return cause
    return None


def _draw_amount(rng: Random) -> int:
    total = sum(weight for _, weight in _AMOUNT_TIERS)
    roll = rng.random() * total
    cumulative = 0
    for amount, weight in _AMOUNT_TIERS:
        cumulative += weight
        if roll < cumulative:
            return amount
    return _AMOUNT_TIERS[0][0]  # pragma: no cover - float edge never reached


def generate_cohort(n: int = 500, seed: int = 42) -> list[SimSubscriber]:
    """Deterministic cohort: same (n, seed) always yields the identical list."""
    rng = Random(seed)
    cohort: list[SimSubscriber] = []
    for i in range(n):
        cause = _draw_cause(rng)
        amount_minor = _draw_amount(rng)
        code = None if cause is None else _FAILURE_CODES[cause]
        description = (
            _UNKNOWN_DESCRIPTION if cause is None else _FAILURE_DESCRIPTIONS[cause]
        )
        cohort.append(
            SimSubscriber(
                subscription_id=f"sub_sim_{i:04d}",
                customer_id=f"cust_sim_{i:04d}",
                amount_minor=amount_minor,
                failure_code=code,
                error_description=description,
            )
        )
    return cohort


def root_cause_of(subscriber: SimSubscriber) -> str:
    """Taxonomy root cause for a subscriber; unmapped/absent codes are UNKNOWN."""
    return ERROR_CODE_MAP.get(subscriber.failure_code or "", UNKNOWN)


def webhook_payload(subscriber: SimSubscriber) -> dict[str, Any]:
    """Razorpay-shaped payment-failure payload for the ingest/engine boundary."""
    return {
        "subscription_id": subscriber.subscription_id,
        "customer_id": subscriber.customer_id,
        "failure_code": subscriber.failure_code or SIM_UNKNOWN_CODE,
        "error_description": subscriber.error_description,
        "amount_minor": subscriber.amount_minor,
        "currency": "INR",
    }
