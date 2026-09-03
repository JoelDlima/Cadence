"""Mandate retry sequencer.

A failed UPI AutoPay or card e-mandate needs an intelligent
sequencer: the next step depends on the cause, the recency of
similar failures, and the time-since-mandate-paused state. The
engine + Adaptive Recovery Brain + Guardian already gate every
action; this module just decides the *cadence* and the *rail*.

Sequencer ladder:
  RETRY_NOW (cause != BANK_DOWN)              -> same-day retry
  RETRY_24H (cause = BANK_DOWN)               -> wait 24h for bank cooling
  REMITTER_OUTREACH (3+ BANK_DOWN in 7d)      -> ask customer to use a different bank
  SWITCH_METHOD (mandate paused > 14d)        -> nudge the customer to re-mandate
  STOP_AND_HUMAN_REVIEW (3+ distinct causes)  -> hand to a human
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


# Action constants — keep in lock-step with the engine's
# RETRY_NOW, RETRY_PAYDAY, etc. The sequencer outputs a subset.
ACTION_RETRY_NOW = "RETRY_NOW"
ACTION_RETRY_24H = "RETRY_24H"
ACTION_REMITTER_OUTREACH = "REMITTER_OUTREACH"
ACTION_SWITCH_METHOD = "SWITCH_METHOD"
ACTION_STOP_AND_HUMAN_REVIEW = "STOP_AND_HUMAN_REVIEW"

VALID_ACTIONS = frozenset({
    ACTION_RETRY_NOW,
    ACTION_RETRY_24H,
    ACTION_REMITTER_OUTREACH,
    ACTION_SWITCH_METHOD,
    ACTION_STOP_AND_HUMAN_REVIEW,
})

# Heuristics
BANK_DOWN_7D_THRESHOLD = 3
MANDATE_PAUSED_THRESHOLD = timedelta(days=14)
DISTINCT_CAUSES_HUMAN_THRESHOLD = 3

# When the sequencer picks RETRY_24H, this is the delay before
# the next debit attempt.
RETRY_24H_DELAY = timedelta(hours=24)


@dataclass(frozen=True)
class MandateFailure:
    """One recent mandate failure, with the cause and timestamp."""
    cause: str
    occurred_at: datetime


@dataclass(frozen=True)
class MandateState:
    id: str
    customer_id: str
    status: str          # 'active', 'paused', 'revoked', 'failed'
    paused_at: datetime | None
    recent_failures: tuple[MandateFailure, ...]


@dataclass(frozen=True)
class SequencerDecision:
    action: str
    schedule_after: timedelta
    reason: str


def _distinct_causes(failures: tuple[MandateFailure, ...]) -> set[str]:
    return {f.cause for f in failures}


def _bank_down_in_window(
    failures: tuple[MandateFailure, ...],
    now: datetime,
    window: timedelta,
) -> int:
    cutoff = now - window
    return sum(1 for f in failures if f.cause == "BANK_DOWN" and f.occurred_at >= cutoff)


def decide(
    state: MandateState,
    *,
    now: datetime,
    cause: str,
) -> SequencerDecision:
    """Decide the next step for a failed mandate.

    Pure function. The caller is responsible for reading the
    mandate state, calling decide, and writing the result back.
    """
    # Human review: 3+ distinct causes in the recent history.
    if len(_distinct_causes(state.recent_failures)) >= DISTINCT_CAUSES_HUMAN_THRESHOLD:
        return SequencerDecision(
            action=ACTION_STOP_AND_HUMAN_REVIEW,
            schedule_after=timedelta(0),
            reason=(
                f"{DISTINCT_CAUSES_HUMAN_THRESHOLD}+ distinct causes "
                f"({sorted(_distinct_causes(state.recent_failures))}), needs human"
            ),
        )

    # Remitter outreach: 3+ BANK_DOWN in 7d.
    if _bank_down_in_window(state.recent_failures, now, timedelta(days=7)) >= BANK_DOWN_7D_THRESHOLD:
        return SequencerDecision(
            action=ACTION_REMITTER_OUTREACH,
            schedule_after=timedelta(0),
            reason=(
                f"{BANK_DOWN_7D_THRESHOLD}+ BANK_DOWN failures in last 7d, "
                "ask customer to switch remitter bank"
            ),
        )

    # Switch method: mandate paused > 14d.
    if (
        state.status == "paused"
        and state.paused_at is not None
        and (now - state.paused_at) >= MANDATE_PAUSED_THRESHOLD
    ):
        return SequencerDecision(
            action=ACTION_SWITCH_METHOD,
            schedule_after=timedelta(0),
            reason=(
                f"mandate paused for {(now - state.paused_at).days}d, "
                "nudge customer to re-mandate"
            ),
        )

    # Bank-down 24h retry.
    if cause == "BANK_DOWN":
        return SequencerDecision(
            action=ACTION_RETRY_24H,
            schedule_after=RETRY_24H_DELAY,
            reason="BANK_DOWN: wait 24h for bank cooling",
        )

    # Default: same-day retry for any other cause.
    return SequencerDecision(
        action=ACTION_RETRY_NOW,
        schedule_after=timedelta(0),
        reason=f"cause={cause}: same-day retry",
    )


__all__ = [
    "ACTION_REMITTER_OUTREACH",
    "ACTION_RETRY_24H",
    "ACTION_RETRY_NOW",
    "ACTION_STOP_AND_HUMAN_REVIEW",
    "ACTION_SWITCH_METHOD",
    "BANK_DOWN_7D_THRESHOLD",
    "DISTINCT_CAUSES_HUMAN_THRESHOLD",
    "MANDATE_PAUSED_THRESHOLD",
    "MandateFailure",
    "MandateState",
    "RETRY_24H_DELAY",
    "SequencerDecision",
    "VALID_ACTIONS",
    "decide",
]
