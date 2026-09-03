"""Shared contracts between the journey engine (scheduler) and executors.

These frozen dataclasses are the ONLY interface between Wave modules — engine
enqueues `TASK_EXECUTE_INTENT` tasks; the worker dispatches them to
`Dispatcher.execute`; outcome checks loop back as new failure events.
"""

from __future__ import annotations

from dataclasses import dataclass

TASK_HANDLE_PAYMENT_FAILED = "handle_payment_failed"
TASK_EXECUTE_INTENT = "execute_intervention"
TASK_OUTCOME_CHECK = "outcome_check"
TASK_AWAIT_CUSTOMER_REPLY = "await_customer_reply"
TASK_PAYMENT_CAPTURED = "payment_captured"

STATUS_EXECUTED = "executed"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class InterventionRequest:
    journey_id: str
    subscription_id: str
    customer_id: str
    intervention: str  # one of taxonomy INTERVENTIONS
    amount_minor: int
    currency: str
    attempt_no: int  # 1-based recovery attempt counter
    scheduled_at: str  # ISO UTC when this became due


@dataclass(frozen=True)
class InterventionResult:
    status: str  # STATUS_* constant
    detail: str
    ref: str | None = None  # e.g. payment link id / retry reference


def request_from_payload(payload: dict) -> InterventionRequest:
    return InterventionRequest(
        journey_id=str(payload["journey_id"]),
        subscription_id=str(payload["subscription_id"]),
        customer_id=str(payload.get("customer_id", "unknown")),
        intervention=str(payload["intervention"]),
        amount_minor=int(payload.get("amount_minor", 0)),
        currency=str(payload.get("currency", "INR")),
        attempt_no=int(payload.get("attempt_no", 1)),
        scheduled_at=str(payload.get("scheduled_at", "")),
    )
