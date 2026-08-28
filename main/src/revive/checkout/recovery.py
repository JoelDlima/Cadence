"""Checkout drop-off recovery.

When a customer opens a Razorpay checkout but doesn't pay within a
window, this chaser sends a soft reminder. The chaser respects the
same NPCI quiet-hours and touch-cap as the consumer recovery path.
Pure functions only: no I/O, no clock reads (clock is injected).

The chaser ladder is:
  OPEN (just started) -> nothing yet
  ABANDONED (>= 30 min, no payment_link.paid) -> ready for nudge
  NUDGED (>= 1 nudge sent) -> wait NUDGE_T1_AFTER, send nudge 2
                              wait NUDGE_T2_AFTER, send nudge 3
                              the 3rd nudge includes a 5% discount
  RECOVERED (payment_link.paid webhook arrived) -> stop
  EXPIRED (no recovery after 14 d) -> stop
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC


# State machine constants.
STATUS_OPEN = "OPEN"
STATUS_ABANDONED = "ABANDONED"
STATUS_NUDGED = "NUDGED"
STATUS_RECOVERED = "RECOVERED"
STATUS_EXPIRED = "EXPIRED"

VALID_STATUSES = frozenset({
    STATUS_OPEN, STATUS_ABANDONED, STATUS_NUDGED,
    STATUS_RECOVERED, STATUS_EXPIRED,
})

# How long we wait for the customer to pay before we consider
# the session "abandoned". 30 min matches Razorpay's typical
# payment-link expiry window.
ABANDON_AFTER = timedelta(minutes=30)

# The chaser ladder delays.
NUDGE_T1_AFTER = timedelta(hours=24)
NUDGE_T2_AFTER = timedelta(days=7)

# Maximum nudges we'll ever send for a single abandoned session.
MAX_NUDGES = 3

# After this, we give up and EXPIRE the session.
EXPIRE_AFTER = timedelta(days=14)


@dataclass(frozen=True)
class CheckoutSession:
    """Snapshot of a checkout session row for the state machine."""
    id: str
    customer_id: str
    amount_minor: int
    status: str
    started_at: datetime
    abandoned_at: datetime | None
    last_nudge_at: datetime | None
    nudges_sent: int


@dataclass(frozen=True)
class ChaseDecision:
    """Pure result of the chaser deciding what to do next."""
    next_status: str              # what to write into checkout_sessions.status
    should_nudge: bool            # True iff a new nudge should fire now
    include_discount: bool        # True iff the next nudge should include a 5% discount
    reason: str                   # human-readable, audit chain friendly


def decide(
    session: CheckoutSession,
    now: datetime,
    paid_event: bool = False,
) -> ChaseDecision:
    """Compute the next state for a checkout session.

    Pure function. The caller is responsible for reading the row
    into a CheckoutSession, calling decide, and writing the result
    back. The audit chain captures every transition.

    `paid_event` is True when a `payment_link.paid` webhook has
    just arrived for this session.
    """
    if paid_event:
        return ChaseDecision(
            next_status=STATUS_RECOVERED,
            should_nudge=False,
            include_discount=False,
            reason="payment_link.paid webhook arrived",
        )

    if session.status in (STATUS_RECOVERED, STATUS_EXPIRED):
        return ChaseDecision(
            next_status=session.status,
            should_nudge=False,
            include_discount=False,
            reason=f"terminal state {session.status}",
        )

    # Hard expire ceiling: if we waited too long even at NUDGED, give up.
    if (now - session.started_at) >= EXPIRE_AFTER:
        return ChaseDecision(
            next_status=STATUS_EXPIRED,
            should_nudge=False,
            include_discount=False,
            reason=f"hit EXPIRE_AFTER={EXPIRE_AFTER}",
        )

    if session.status == STATUS_OPEN:
        if (now - session.started_at) >= ABANDON_AFTER or session.abandoned_at is not None:
            return ChaseDecision(
                next_status=STATUS_ABANDONED,
                should_nudge=True,
                include_discount=False,
                reason="abandon threshold reached (30 min, no payment)",
            )
        return ChaseDecision(
            next_status=STATUS_OPEN,
            should_nudge=False,
            include_discount=False,
            reason="still in checkout window",
        )

    if session.status == STATUS_ABANDONED:
        # First nudge fires immediately on transition to ABANDONED.
        return ChaseDecision(
            next_status=STATUS_NUDGED,
            should_nudge=True,
            include_discount=False,
            reason="first nudge (T0)",
        )

    if session.status == STATUS_NUDGED:
        if session.nudges_sent >= MAX_NUDGES:
            return ChaseDecision(
                next_status=STATUS_EXPIRED,
                should_nudge=False,
                include_discount=False,
                reason=f"hit MAX_NUDGES={MAX_NUDGES}",
            )
        if session.last_nudge_at is None:
            return ChaseDecision(
                next_status=STATUS_NUDGED,
                should_nudge=True,
                include_discount=False,
                reason="defensive nudge (NUDGED with no last_nudge_at)",
            )
        if session.nudges_sent == 1 and (now - session.last_nudge_at) < NUDGE_T1_AFTER:
            return ChaseDecision(
                next_status=STATUS_NUDGED,
                should_nudge=False,
                include_discount=False,
                reason=f"too soon for nudge 2 (need {NUDGE_T1_AFTER})",
            )
        if session.nudges_sent == 2 and (now - session.last_nudge_at) < NUDGE_T2_AFTER:
            return ChaseDecision(
                next_status=STATUS_NUDGED,
                should_nudge=False,
                include_discount=False,
                reason=f"too soon for nudge 3 (need {NUDGE_T2_AFTER})",
            )
        next_nudge_number = session.nudges_sent + 1
        include_discount = next_nudge_number >= MAX_NUDGES
        return ChaseDecision(
            next_status=STATUS_NUDGED,
            should_nudge=True,
            include_discount=include_discount,
            reason=f"nudge #{next_nudge_number} (touch-cap respected)",
        )

    return ChaseDecision(
        next_status=session.status,
        should_nudge=False,
        include_discount=False,
        reason=f"unknown status {session.status!r}, no-op",
    )


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


__all__ = [
    "ABANDON_AFTER",
    "EXPIRE_AFTER",
    "MAX_NUDGES",
    "NUDGE_T1_AFTER",
    "NUDGE_T2_AFTER",
    "ChaseDecision",
    "CheckoutSession",
    "STATUS_ABANDONED",
    "STATUS_EXPIRED",
    "STATUS_NUDGED",
    "STATUS_OPEN",
    "STATUS_RECOVERED",
    "VALID_STATUSES",
    "decide",
    "utcnow",
]
